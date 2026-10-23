"""Camera-calibrated traffic suggestions. These rules are not a trained classifier."""

import csv
import json
import math
import shutil
from datetime import datetime, timezone
from ..database.store import connect
from ..core.config import CLASSES
from ..dataset.exports import new_destination, split_groups, finish_export
from ..dataset.operations import copy_image

TRAFFIC_CLASSES = ["Thong_thoang", "Dong_xe", "Un_u_nhe", "Un_tac_nang"]


def inside(pt, poly):
    x, y = pt
    result = False
    j = len(poly) - 1
    for i, (xi, yi) in enumerate(poly):
        xj, yj = poly[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi + 1e-15) + xi:
            result = not result
        j = i
    return result


def polygon_area(poly):
    return (
        abs(
            sum(
                poly[i][0] * poly[(i + 1) % len(poly)][1]
                - poly[(i + 1) % len(poly)][0] * poly[i][1]
                for i in range(len(poly))
            )
        )
        / 2
    )


def get_roi(cam):
    with connect() as db:
        row = db.execute(
            "SELECT config FROM camera_configs WHERE camera_id=?", (cam,)
        ).fetchone()
    return json.loads(row[0]) if row else None


def save_roi(cam, cfg):
    if not cam or len(cam) > 120 or not isinstance(cfg, dict):
        raise ValueError("Camera/cấu hình không hợp lệ.")
    rois = cfg.get("rois", [])
    if not isinstance(rois, list) or len(rois) > 30:
        raise ValueError("ROI phải là danh sách, tối đa 30 vùng.")
    for roi in rois:
        if not isinstance(roi, dict) or roi.get("type") not in (
            "road",
            "lane",
            "exclusion",
            "queue",
        ):
            raise ValueError("Loại ROI phải là road/lane/exclusion/queue.")
        poly = roi.get("polygon", [])
        if not 3 <= len(poly) <= 100:
            raise ValueError("ROI cần 3–100 điểm.")
        if any(
            not isinstance(p, (list, tuple))
            or len(p) != 2
            or any(
                not isinstance(v, (int, float))
                or not math.isfinite(v)
                or not 0 <= v <= 1
                for v in p
            )
            for p in poly
        ):
            raise ValueError("Điểm ROI cần tọa độ hữu hạn trong 0–1.")
        if polygon_area(poly) <= 1e-6:
            raise ValueError("ROI không có diện tích. Hãy vẽ lại vùng đường.")

        def cross(a, b, c):
            return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])

        for i in range(len(poly)):
            for j in range(i + 2, len(poly)):
                if i == 0 and j == len(poly) - 1:
                    continue
                a, b, c, d = (
                    poly[i],
                    poly[(i + 1) % len(poly)],
                    poly[j],
                    poly[(j + 1) % len(poly)],
                )
                if (
                    cross(a, b, c) * cross(a, b, d) < 0
                    and cross(c, d, a) * cross(c, d, b) < 0
                ):
                    raise ValueError(
                        "ROI tự cắt nhau. Hãy đặt điểm theo thứ tự quanh biên."
                    )
    cal = cfg.get("calibration", {})
    if not isinstance(cal, dict):
        raise ValueError("Ngưỡng hiệu chuẩn phải là object.")
    if cal:
        values = [cal.get(k) for k in ("free_max", "busy_max", "jam_min")]
        if (
            not all(isinstance(v, (int, float)) and math.isfinite(v) for v in values)
            or not 0 <= values[0] < values[1] < values[2]
        ):
            raise ValueError("Ngưỡng cần tăng dần: 0 ≤ free_max < busy_max < jam_min.")
        if "queue_min" in cal and not (
            isinstance(cal["queue_min"], (int, float))
            and values[1] < cal["queue_min"] <= values[2]
        ):
            raise ValueError("queue_min cần lớn hơn busy_max và không vượt jam_min.")
    result = {
        "rois": rois,
        "calibration": cal,
        "calibration_confirmed": bool(cfg.get("calibration_confirmed", False)),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    with connect() as db:
        db.execute(
            "INSERT INTO camera_configs(camera_id,config) VALUES(?,?) ON CONFLICT(camera_id) DO UPDATE SET config=excluded.config,updated_at=CURRENT_TIMESTAMP",
            (cam, json.dumps(result, ensure_ascii=False)),
        )
        # ROI changes invalidate counts, not an independent human classification.
        for row in db.execute(
            "SELECT image_id,features_json FROM traffic_measurements WHERE camera_id=?",
            (cam,),
        ).fetchall():
            features = json.loads(row["features_json"])
            features["features_stale"] = True
            db.execute(
                "UPDATE traffic_measurements SET features_json=? WHERE image_id=?",
                (json.dumps(features, ensure_ascii=False), row["image_id"]),
            )
    return result


def cameras():
    with connect() as db:
        return [
            dict(r)
            for r in db.execute(
                "SELECT camera_id,count(*) image_count,min(timestamp) first_timestamp,max(timestamp) last_timestamp,min(id) preview_id FROM images GROUP BY camera_id ORDER BY camera_id"
            )
        ]


def analyze_all(progress=None, checkpoint=None):
    progress = progress or (lambda *args: None)
    with connect() as db:
        ids = [
            r[0]
            for r in db.execute("SELECT id FROM images ORDER BY camera_id,timestamp,id")
        ]
        configs = {
            r["camera_id"]: json.loads(r["config"])
            for r in db.execute("SELECT * FROM camera_configs")
        }
    labeled = needs_review = 0
    examples = []
    processed = 0
    for index, iid in enumerate(ids, 1):
        if checkpoint and not checkpoint():
            break
        processed += 1
        with connect() as db:
            db.execute("BEGIN IMMEDIATE")
            im = db.execute("SELECT * FROM images WHERE id=?", (iid,)).fetchone()
            cfg = configs.get(im["camera_id"], {})
            rois = [
                r
                for r in cfg.get("rois", [])
                if r.get("status", "confirmed") == "confirmed"
            ]
            roads = [r["polygon"] for r in rois if r["type"] == "road"]
            excluded = [r["polygon"] for r in rois if r["type"] == "exclusion"]
            annotations = db.execute(
                "SELECT * FROM annotations WHERE image_id=? AND NOT(reviewed=1 AND accepted=0)",
                (iid,),
            ).fetchall()
            counts = {name: 0 for name in CLASSES}
            uncertain = pending = 0
            box_area = 0
            for ann in annotations:
                center = (
                    (ann["x1"] + ann["x2"]) / (2 * im["width"]),
                    (ann["y1"] + ann["y2"]) / (2 * im["height"]),
                )
                if roads and not any(inside(center, p) for p in roads):
                    continue
                if any(inside(center, p) for p in excluded):
                    continue
                if ann["class_name"] in counts:
                    counts[ann["class_name"]] += 1
                else:
                    uncertain += 1
                if not ann["accepted"]:
                    pending += 1
                box_area += max(0, ann["x2"] - ann["x1"]) * max(
                    0, ann["y2"] - ann["y1"]
                )
            total = sum(counts.values())
            # Sum of box areas is explicitly a proxy, not mask union / exact road occupancy.
            area = sum(polygon_area(p) for p in roads) * im["width"] * im["height"]
            occupancy = min(1, box_area / area) if area else None
            cal = cfg.get("calibration", {})
            reasons = []
            if not roads:
                reasons.append("missing_confirmed_road_roi")
            if not im["timestamp"]:
                reasons.append("missing_timestamp_image_only_mode")
            if not annotations and im["review_state"] != "negative":
                reasons.append("missing_detection_annotations")
            if pending:
                reasons.append("unreviewed_detection_proposals")
            if uncertain:
                reasons.append("uncertain_vehicle_count")
            if not cal or not cfg.get("calibration_confirmed"):
                reasons.append("camera_thresholds_not_calibrated")
            rule = None
            if cal and (
                annotations
                or im["status"] == "processed"
                or im["review_state"] == "negative"
            ):
                rule = (
                    TRAFFIC_CLASSES[0]
                    if total <= cal["free_max"]
                    else (
                        TRAFFIC_CLASSES[1]
                        if total <= cal["busy_max"]
                        else (
                            TRAFFIC_CLASSES[2]
                            if total < cal["jam_min"]
                            else TRAFFIC_CLASSES[3]
                        )
                    )
                )
            quality = (
                "high_quality_candidate"
                if roads
                and cal
                and cfg.get("calibration_confirmed")
                and (annotations or im["review_state"] == "negative")
                and not uncertain
                and not pending
                else "needs_review"
            )
            features = {
                "camera_id": im["camera_id"],
                "timestamp": im["timestamp"],
                "counts": counts,
                "total_vehicle_count": total,
                "uncertain_vehicle_count": uncertain,
                "pending_detection_count": pending,
                "road_pixel_occupancy": None,
                "box_occupancy_proxy": occupancy,
                "occupancy_source": (
                    "bounding_box_area_proxy"
                    if occupancy is not None
                    else "unavailable"
                ),
                "relative_density": total if roads else None,
                "queue_indicator": "unavailable",
                "predicted_rule_class": rule,
                "predicted_traffic_class": rule,
                "class_id": TRAFFIC_CLASSES.index(rule) if rule else None,
                "quality_score": None,
                "review_status": quality,
                "label_source": "camera_rule_pseudo_label" if rule else "unavailable",
                "reasons": reasons,
                "image_path": im["path"],
                "annotation_version": im["review_version"],
                "features_stale": False,
            }
            old = db.execute(
                "SELECT * FROM traffic_measurements WHERE image_id=?", (iid,)
            ).fetchone()
            label, status = rule, quality
            if (
                old
                and old["review_status"] in ("accepted", "rejected")
                and old["quality"] == "human_verified"
            ):
                old_data = json.loads(old["features_json"])
                label, status, quality = (
                    old["predicted_class"],
                    old["review_status"],
                    "human_verified",
                )
                features.update(
                    predicted_traffic_class=label,
                    class_id=TRAFFIC_CLASSES.index(label),
                    review_status=status,
                    label_source="human_verified",
                    verified_by_human=True,
                    reviewed_annotation_version=old_data.get(
                        "reviewed_annotation_version"
                    ),
                    features_changed_since_review=old_data.get(
                        "reviewed_annotation_version"
                    )
                    != im["review_version"],
                )
            db.execute(
                "INSERT INTO traffic_measurements(image_id,camera_id,timestamp,features_json,predicted_class,quality,review_status) VALUES(?,?,?,?,?,?,?) ON CONFLICT(image_id) DO UPDATE SET camera_id=excluded.camera_id,timestamp=excluded.timestamp,features_json=excluded.features_json,predicted_class=excluded.predicted_class,quality=excluded.quality,review_status=excluded.review_status,updated_at=CURRENT_TIMESTAMP",
                (
                    iid,
                    im["camera_id"],
                    im["timestamp"],
                    json.dumps(features, ensure_ascii=False),
                    label,
                    quality,
                    status,
                ),
            )
            labeled += bool(label)
            needs_review += status not in ("accepted", "rejected")
            if len(examples) < 100:
                examples.append(
                    {"image_id": iid, "rel_path": im["rel_path"], **features}
                )
        if index % 25 == 0 or index == len(ids):
            progress(index, len(ids), f"Đã phân tích {index:,}/{len(ids):,} ảnh")
    return {
        "processed": processed,
        "labeled": labeled,
        "needs_review": needs_review,
        "items": examples,
    }


def list_labels(limit=100, review_only=False, offset=0, q="", camera=""):
    where, args = [], []
    if review_only:
        where.append("t.review_status NOT IN ('accepted','rejected')")
    if q:
        where.append("i.rel_path LIKE ?")
        args.append("%" + q + "%")
    if camera:
        where.append("t.camera_id=?")
        args.append(camera)
    sql = (
        "SELECT t.*,i.rel_path FROM traffic_measurements t JOIN images i ON i.id=t.image_id"
        + (" WHERE " + " AND ".join(where) if where else "")
        + " ORDER BY t.camera_id,COALESCE(t.timestamp,''),t.image_id"
    )
    if limit is not None:
        sql += " LIMIT ? OFFSET ?"
        args.extend([max(1, min(limit, 500)), max(0, offset)])
    with connect() as db:
        return [dict(r) for r in db.execute(sql, args)]


def set_label(iid, label, accepted=True):
    if label not in TRAFFIC_CLASSES:
        raise ValueError("Nhãn giao thông không hợp lệ.")
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute(
            "SELECT features_json FROM traffic_measurements WHERE image_id=?", (iid,)
        ).fetchone()
        if not row:
            raise ValueError("Chưa phân tích ảnh. Chạy phân tích traffic trước.")
        features = json.loads(row[0])
        features.update(
            predicted_traffic_class=label,
            class_id=TRAFFIC_CLASSES.index(label),
            review_status="accepted" if accepted else "rejected",
            label_source="human_verified",
            verified_by_human=True,
            reviewed_annotation_version=features.get("annotation_version"),
        )
        db.execute(
            "UPDATE traffic_measurements SET features_json=?,predicted_class=?,quality='human_verified',review_status=?,updated_at=CURRENT_TIMESTAMP WHERE image_id=?",
            (
                json.dumps(features, ensure_ascii=False),
                label,
                features["review_status"],
                iid,
            ),
        )
        db.execute(
            "INSERT INTO events(image_id,level,message) VALUES(?,'info',?)",
            (iid, f'Classification: {label} ({features["review_status"]})'),
        )
    return {"image_id": iid, "label": label, "review_status": features["review_status"]}


def temporal_records():
    rows = list_labels(limit=None)  # No pagination at the export boundary.
    output, previous = [], {}
    for row in rows:
        if not row["timestamp"]:
            continue
        try:
            timestamp = datetime.fromisoformat(row["timestamp"])
        except ValueError:
            continue
        features = json.loads(row["features_json"])
        if features.get("features_stale"):
            raise ValueError(
                "Đặc trưng đã thay đổi do review/ROI. Chạy phân tích lại trước khi xuất CSV."
            )
        prev = previous.get(row["camera_id"])
        try:
            delta = (timestamp - prev[0]).total_seconds() if prev else None
        except TypeError:
            delta = None
        record = {
            "camera_id": row["camera_id"],
            "timestamp": timestamp.isoformat(sep=" "),
            "interval_seconds": delta,
            "gap_over_13s": bool(delta is not None and delta > 13),
        }
        record.update(
            {name + "_count": features["counts"].get(name, 0) for name in CLASSES}
        )
        record.update(
            total_vehicle_count=features["total_vehicle_count"],
            road_pixel_occupancy=None,
            box_occupancy_proxy=features["box_occupancy_proxy"],
            relative_density=features["relative_density"],
            density_trend=features["total_vehicle_count"] - prev[1] if prev else None,
            traffic_class_id=(
                TRAFFIC_CLASSES.index(row["predicted_class"])
                if row["predicted_class"] in TRAFFIC_CLASSES
                else None
            ),
            traffic_class_name=row["predicted_class"],
            classification_quality=row["quality"],
            review_status=row["review_status"],
            label_source=features["label_source"],
            image_path=features["image_path"],
            annotation_version=features["annotation_version"],
            observed=True,
            interpolated=False,
            carried_forward=False,
        )
        output.append(record)
        previous[row["camera_id"]] = (timestamp, features["total_vehicle_count"])
    return output


def export_traffic(name="traffic", mode="extended", progress=None):
    if mode != "extended":
        raise ValueError(
            "Chỉ hỗ trợ extended; chưa có schema/normalizer TCN được xác minh."
        )
    rows = temporal_records()
    if not rows:
        raise ValueError("Chưa có timestamp hợp lệ để xuất chuỗi.")
    dest = new_destination("traffic_" + name)
    try:
        with (dest / "traffic_extended.csv").open(
            "w", newline="", encoding="utf-8-sig"
        ) as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
        with connect() as db:
            total = db.execute("SELECT count(*) FROM traffic_measurements").fetchone()[
                0
            ]
        (dest / "schema.json").write_text(
            json.dumps(
                {
                    "mode": "extended_traffic_features",
                    "legacy_compatible": False,
                    "timestamp_policy": "observed only; no synthetic steps; naive timestamps retain source local time",
                    "pseudo_labels_are_not_ground_truth": True,
                    "missing_timestamp_skipped": total - len(rows),
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        return finish_export(
            dest,
            "temporal",
            {
                "records": len(rows),
                "mode": "extended",
                "legacy_compatible": False,
                "skipped": total - len(rows),
            },
        )
    except Exception:
        shutil.rmtree(dest, ignore_errors=True)
        dest.with_suffix(".zip").unlink(missing_ok=True)
        raise


def export_classification(
    name="traffic_classification", include_pseudo=False, progress=None
):
    progress = progress or (lambda *args: None)
    with connect() as db:
        rows = [
            dict(r)
            for r in db.execute(
                "SELECT t.*,i.path,i.sha256,i.rel_path FROM traffic_measurements t JOIN images i ON i.id=t.image_id WHERE t.predicted_class IS NOT NULL ORDER BY t.image_id"
            )
        ]
    chosen = []
    for row in rows:
        features = json.loads(row["features_json"])
        human = (
            row["review_status"] == "accepted"
            and features.get("label_source") == "human_verified"
        )
        pseudo = (
            include_pseudo
            and row["review_status"] == "high_quality_candidate"
            and not features.get("features_stale")
        )
        if human or pseudo:
            chosen.append((row, features, not human))
    if not chosen:
        raise ValueError(
            "Chưa có classification đã duyệt. Xác nhận nhãn trên trang Traffic trước khi xuất."
        )
    from pathlib import Path

    for row, _, _ in chosen:
        if not Path(row["path"]).is_file():
            raise ValueError("Ảnh nguồn bị thiếu: " + row["rel_path"])
    splits, groups, warnings = split_groups([row for row, _, _ in chosen])
    dest = new_destination("classification_" + name)
    try:
        for split in ("train", "val"):
            for cls in TRAFFIC_CLASSES:
                (dest / split / cls).mkdir(parents=True)
        manifest = []
        for n, (row, features, pseudo) in enumerate(chosen, 1):
            iid = row["image_id"]
            target = (
                dest
                / splits[iid]
                / row["predicted_class"]
                / f"{iid:08d}_{Path(row['path']).name}"
            )
            copy_image(row["path"], target)
            manifest.append(
                {
                    "image_id": iid,
                    "source": row["path"],
                    "file": target.relative_to(dest).as_posix(),
                    "camera_id": row["camera_id"],
                    "timestamp": row["timestamp"],
                    "group": groups[iid],
                    "class": row["predicted_class"],
                    "label_source": features["label_source"],
                    "pseudo_label": pseudo,
                    "split": splits[iid],
                }
            )
            if n % 25 == 0 or n == len(chosen):
                progress(
                    n,
                    len(chosen),
                    f"Đang đóng gói {n:,}/{len(chosen):,} ảnh classification",
                )
        (dest / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return finish_export(
            dest,
            "classification",
            {
                "images": len(chosen),
                "pseudo_labels": sum(p for _, _, p in chosen),
                "split_method": "camera_day",
                "train": sum(s == "train" for s in splits.values()),
                "val": sum(s == "val" for s in splits.values()),
                "warnings": warnings,
            },
        )
    except Exception:
        shutil.rmtree(dest, ignore_errors=True)
        dest.with_suffix(".zip").unlink(missing_ok=True)
        raise
