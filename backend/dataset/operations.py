"""Dataset intake and review-aware YOLO exports."""

import hashlib
import json
import math
import re
import shutil
import sqlite3
import yaml
from datetime import datetime, timezone
from pathlib import Path
from PIL import Image, ImageOps, UnidentifiedImageError
from ..core.config import IMAGE_EXTS, CLASSES, DATA_ROOT
from ..database.store import connect
from .exports import new_destination, split_groups, finish_export


def backup_database():
    folder = DATA_ROOT / "backups"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / (
        "before-clear-"
        + datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S%f")
        + ".sqlite3"
    )
    with connect() as db, sqlite3.connect(path) as target:
        db.backup(target)
    return str(path)


def clear_dataset():
    backup = backup_database()
    with connect() as db:
        # Keep identifiers monotonic after replacement: an old browser tab must
        # never save an old annotation onto a newly imported image with the same ID.
        last_id = db.execute("SELECT coalesce(max(id),0) FROM images").fetchone()[0]
        db.execute(
            "INSERT INTO workspace_meta(key,value) VALUES('last_image_id',?) ON CONFLICT(key) DO UPDATE SET value=max(value,excluded.value)",
            (last_id,),
        )
        db.execute("DELETE FROM images")
        db.execute("DELETE FROM annotation_history")
        db.execute("DELETE FROM events")
        db.execute(
            "UPDATE jobs SET state='cancelled',current_path=NULL,updated_at=CURRENT_TIMESTAMP WHERE state IN ('running','paused','stopped','failed')"
        )
    return {
        "cleared": True,
        "backup": backup,
        "message": "Đã làm mới workspace. Ảnh nguồn được giữ nguyên.",
    }


def label_for(path):
    # Both images/train/camera/frame.jpg and train/images/camera/frame.jpg.
    candidates = []
    for parent in path.parents:
        if parent.name == "images":
            candidates.append(
                (parent.parent / "labels" / path.relative_to(parent)).with_suffix(
                    ".txt"
                )
            )
    candidates.extend(
        [path.parent / "labels" / (path.stem + ".txt"), path.with_suffix(".txt")]
    )
    return next((p for p in candidates if p.is_file()), None)


def class_mapping(root):
    """Honor YOLO data.yaml names instead of silently assuming numeric class order."""
    for parent in (root, *root.parents):
        for filename in ("data.yaml", "dataset.yaml", "data.yml"):
            path = parent / filename
            if not path.is_file():
                continue
            try:
                if path.stat().st_size > 1024 * 1024:
                    raise ValueError("data.yaml quá lớn.")
                content = yaml.safe_load(path.read_text(encoding="utf-8-sig"))
                names = content.get("names") if isinstance(content, dict) else None
                if isinstance(names, list):
                    names = dict(enumerate(names))
                if not isinstance(names, dict) or not names:
                    raise ValueError(
                        "data.yaml cần trường names dạng list hoặc object."
                    )
                mapping = {
                    int(i): str(name).strip().lower() for i, name in names.items()
                }
                return mapping, str(path)
            except (
                yaml.YAMLError,
                OSError,
                UnicodeError,
                TypeError,
                ValueError,
            ) as exc:
                raise ValueError(f"Không đọc được class mapping {path}: {exc}") from exc
    return dict(enumerate(CLASSES)), None


def read_labels(label, width, height, mapping=None):
    boxes, errors = [], []
    mapping = mapping or dict(enumerate(CLASSES))
    if label is None:
        return boxes, errors
    for number, line in enumerate(
        label.read_text(encoding="utf-8-sig").splitlines(), 1
    ):
        if not line.strip():
            continue
        try:
            parts = line.split()
            if len(parts) != 5:
                raise ValueError("cần 5 cột detection, không phải polygon/segmentation")
            original_class = int(parts[0])
            name = mapping.get(original_class)
            if name not in CLASSES:
                raise ValueError(
                    f"class {original_class} ({name}) không nằm trong schema xe hỗ trợ"
                )
            cls = CLASSES.index(name)
            cx, cy, bw, bh = map(float, parts[1:])
            if cls not in range(len(CLASSES)) or not all(
                math.isfinite(v) for v in (cx, cy, bw, bh)
            ):
                raise ValueError("class/tọa độ không hợp lệ")
            x1, y1, x2, y2 = cx - bw / 2, cy - bh / 2, cx + bw / 2, cy + bh / 2
            if (
                bw <= 0
                or bh <= 0
                or x1 < -1e-6
                or y1 < -1e-6
                or x2 > 1 + 1e-6
                or y2 > 1 + 1e-6
            ):
                raise ValueError("box rỗng hoặc vượt biên ảnh")
            boxes.append(
                (
                    cls,
                    [
                        max(0, x1) * width,
                        max(0, y1) * height,
                        min(1, x2) * width,
                        min(1, y2) * height,
                    ],
                    number,
                )
            )
        except (ValueError, IndexError) as exc:
            errors.append(f"{label}:{number}: {exc}")
    return boxes, errors


def import_folder(folder, clear_first=False, progress=None, keep_duplicates=False):
    progress = progress or (lambda *args: None)
    root = Path(folder).expanduser().resolve()
    if not root.is_dir():
        raise ValueError(
            "Thư mục không tồn tại trên máy chạy server. Kiểm tra lại đường dẫn."
        )
    mapping, mapping_source = class_mapping(root)
    files = []
    for path in root.rglob("*"):
        if path.is_file() and path.suffix.lower() in IMAGE_EXTS:
            files.append(path)
            if len(files) % 500 == 0:
                progress(0, 0, f"Đang tìm ảnh: {len(files):,} tệp…")
    files.sort()
    if not files:
        raise ValueError("Không tìm thấy JPG/PNG/WebP/BMP. Dataset cũ được giữ nguyên.")
    if clear_first:
        valid = False
        for path in files:
            try:
                with Image.open(path) as im:
                    im.load()
                valid = True
                break
            except (OSError, ValueError, UnidentifiedImageError):
                continue
        if not valid:
            raise ValueError("Không có ảnh đọc được. Dataset cũ được giữ nguyên.")
        clear_dataset()
    added = duplicates = broken = label_errors = retained_duplicates = 0
    samples = []
    with connect() as db:
        hashes = {r[0] for r in db.execute("SELECT sha256 FROM images")}
        paths = {r[0] for r in db.execute("SELECT path FROM images")}
        next_id = 1 + max(
            db.execute("SELECT coalesce(max(id),0) FROM images").fetchone()[0],
            db.execute(
                "SELECT coalesce((SELECT value FROM workspace_meta WHERE key='last_image_id'),0)"
            ).fetchone()[0],
        )
        for index, path in enumerate(files, 1):
            try:
                if str(path) in paths:
                    duplicates += 1
                    continue
                h = hashlib.sha256()
                with path.open("rb") as handle:
                    for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                        h.update(chunk)
                digest = h.hexdigest()
                if digest in hashes and not keep_duplicates:
                    duplicates += 1
                    continue
                is_duplicate = digest in hashes
                with Image.open(path) as source:
                    source.load()
                    width, height = ImageOps.exif_transpose(source).size
                label = label_for(path)
                try:
                    boxes, errors = read_labels(label, width, height, mapping)
                except (OSError, UnicodeError) as exc:
                    boxes, errors = [], [str(exc)]
                rel = path.relative_to(root)
                dirs = [
                    p
                    for p in rel.parts[:-1]
                    if p.lower() not in ("images", "train", "val", "valid", "test")
                ]
                camera = dirs[0] if dirs else "default"
                match = re.search(r"(?<!\d)(\d{8})[_T-](\d{6})(?!\d)", path.stem)
                timestamp = None
                if match:
                    try:
                        timestamp = datetime.strptime(
                            "".join(match.groups()), "%Y%m%d%H%M%S"
                        ).isoformat(sep=" ")
                    except ValueError:
                        pass
                # An empty imported text file is not automatically a verified negative.
                status = "processed" if label else "pending"
                iid = db.execute(
                    "INSERT INTO images(id,path,rel_path,sha256,width,height,camera_id,timestamp,status,error) VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (
                        next_id,
                        str(path),
                        rel.as_posix(),
                        digest,
                        width,
                        height,
                        camera,
                        timestamp,
                        status,
                        "Nhãn nhập lỗi; cần kiểm duyệt." if errors else None,
                    ),
                ).lastrowid
                next_id += 1
                for cls, box, number in boxes:
                    db.execute(
                        "INSERT INTO annotations(image_id,source,class_name,class_id,x1,y1,x2,y2,quality,accepted,metadata) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                        (
                            iid,
                            "original",
                            CLASSES[cls],
                            cls,
                            *box,
                            "imported",
                            1,
                            json.dumps(
                                {
                                    "label_file": str(label),
                                    "line": number,
                                    "class_mapping": mapping_source or "default_schema",
                                },
                                ensure_ascii=False,
                            ),
                        ),
                    )
                for error in errors:
                    db.execute(
                        "INSERT INTO events(image_id,level,message) VALUES(?,?,?)",
                        (iid, "warning", error[:1500]),
                    )
                label_errors += len(errors)
                samples.extend(errors[: max(0, 10 - len(samples))])
                hashes.add(digest)
                paths.add(str(path))
                added += 1
                retained_duplicates += int(is_duplicate)
            except (
                OSError,
                ValueError,
                UnidentifiedImageError,
                Image.DecompressionBombError,
            ) as exc:
                broken += 1
                message = f"Ảnh lỗi {path}: {exc}"[:1500]
                db.execute(
                    "INSERT INTO events(level,message) VALUES('warning',?)", (message,)
                )
                if len(samples) < 10:
                    samples.append(message)
            finally:
                if index % 25 == 0 or index == len(files):
                    db.commit()  # Release writer before the progress callback opens a connection.
                    progress(
                        index,
                        len(files),
                        f"Đã quét {index:,}/{len(files):,} · Thêm {added:,} · Trùng {duplicates:,} · Lỗi {broken:,}",
                    )
    return {
        "added": added,
        "duplicates": duplicates,
        "broken": broken,
        "label_errors": label_errors,
        "scanned": len(files),
        "warnings": samples,
        "class_mapping": mapping_source or "default_schema",
        "retained_duplicates": retained_duplicates,
    }


def copy_image(source, target):
    """Copy byte-for-byte unless EXIF orientation must be normalized for box geometry."""
    with Image.open(source) as im:
        if im.getexif().get(274, 1) != 1:
            oriented = ImageOps.exif_transpose(im)
            if str(target).lower().endswith((".jpg", ".jpeg")):
                oriented.convert("RGB").save(target, quality=95)
            else:
                oriented.save(target)
            return
    shutil.copy2(source, target)


def export_candidates(include_pseudo=False):
    rows = []
    with connect() as db:
        db.execute("BEGIN")
        all_annotations = {}
        for a in db.execute("SELECT * FROM annotations ORDER BY id"):
            all_annotations.setdefault(a["image_id"], []).append(dict(a))
        for im in db.execute("SELECT * FROM images ORDER BY id"):
            image = dict(im)
            if im["error"]:
                continue
            annotations = all_annotations.get(im["id"], [])
            accepted = [a for a in annotations if a["accepted"]]
            imported = (
                bool(annotations)
                and all(a["source"] == "original" for a in annotations)
                and not im["error"]
            )
            human = im["review_state"] in ("reviewed", "negative")
            # Partial AI acceptance must not turn omitted objects into negatives.
            pseudo = bool(accepted) and len(accepted) == len(annotations)
            if human or imported or (include_pseudo and pseudo):
                if accepted or im["review_state"] == "negative":
                    rows.append(
                        (
                            image,
                            accepted,
                            (
                                "human_reviewed"
                                if human
                                else "imported" if imported else "pseudo_label"
                            ),
                        )
                    )
    return rows


def export_dataset(
    name="export",
    output_dir=None,
    include_pseudo=False,
    split_method="camera_day",
    val_fraction=0.2,
    progress=None,
):
    progress = progress or (lambda *args: None)
    rows = export_candidates(include_pseudo)
    if not rows:
        raise ValueError(
            "Chưa có ảnh đủ điều kiện. Duyệt đầy đủ ảnh hoặc xác nhận ảnh không có xe trước khi xuất."
        )
    for image, anns, policy in rows:
        if not Path(image["path"]).is_file():
            raise ValueError(
                f"Ảnh nguồn bị thiếu: {image['rel_path']}. Khôi phục file trước khi xuất."
            )
        for a in anns:
            coords = [a[k] for k in ("x1", "y1", "x2", "y2")]
            if (
                a["class_id"] not in range(len(CLASSES))
                or not all(math.isfinite(x) for x in coords)
                or not (0 <= coords[0] < coords[2] <= image["width"])
                or not (0 <= coords[1] < coords[3] <= image["height"])
            ):
                raise ValueError(
                    f"Nhãn #{a['id']} không hợp lệ; hãy sửa trước khi xuất."
                )
    splits, groups, warnings = split_groups(
        [i for i, _, _ in rows], split_method, val_fraction
    )
    dest = new_destination(name, output_dir)
    try:
        for split in ("train", "val"):
            for kind in ("images", "labels"):
                (dest / kind / split).mkdir(parents=True)
        manifest = []
        for n, (image, annotations, policy) in enumerate(rows, 1):
            iid = image["id"]
            split = splits[iid]
            filename = f"{iid:08d}_{Path(image['path']).name}"
            copy_image(image["path"], dest / "images" / split / filename)
            width, height = image["width"], image["height"]
            lines = [
                f"{a['class_id']} {(a['x1']+a['x2'])/(2*width):.7f} {(a['y1']+a['y2'])/(2*height):.7f} {(a['x2']-a['x1'])/width:.7f} {(a['y2']-a['y1'])/height:.7f}"
                for a in annotations
            ]
            (dest / "labels" / split / (Path(filename).stem + ".txt")).write_text(
                "\n".join(lines) + ("\n" if lines else ""), encoding="utf-8"
            )
            manifest.append(
                {
                    "image_id": iid,
                    "source": image["path"],
                    "file": f"images/{split}/{filename}",
                    "sha256_source": image["sha256"],
                    "group": groups[iid],
                    "split": split,
                    "labels": len(lines),
                    "review_state": image["review_state"],
                    "review_version": image["review_version"],
                    "acceptance_policy": policy,
                }
            )
            if n % 25 == 0 or n == len(rows):
                progress(n, len(rows), f"Đang đóng gói {n:,}/{len(rows):,} ảnh")
        # Relative to data.yaml, not process working directory.
        yaml = "train: images/train\nval: images/val\nnames:\n" + "".join(
            f"  {i}: {value}\n" for i, value in enumerate(CLASSES)
        )
        (dest / "data.yaml").write_text(yaml, encoding="utf-8")
        (dest / "classes.txt").write_text("\n".join(CLASSES) + "\n", encoding="utf-8")
        (dest / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        (dest / "README.txt").write_text(
            "YOLO Detection snapshot. Negative images require explicit human confirmation.\nImported labels retain imported provenance; pseudo labels require opt-in.\nEXIF-rotated images are normalized to match box coordinates.\n"
            + "\n".join(warnings),
            encoding="utf-8",
        )
        return finish_export(
            dest,
            "detection",
            {
                "images": len(rows),
                "negative_images": sum(not a for _, a, _ in rows),
                "classes": CLASSES,
                "data_yaml": str(dest / "data.yaml"),
                "split_method": split_method,
                "train": sum(s == "train" for s in splits.values()),
                "val": sum(s == "val" for s in splits.values()),
                "warnings": warnings,
                "pseudo_labels": sum(p == "pseudo_label" for _, _, p in rows),
            },
        )
    except Exception:
        shutil.rmtree(dest, ignore_errors=True)
        dest.with_suffix(".zip").unlink(missing_ok=True)
        raise
