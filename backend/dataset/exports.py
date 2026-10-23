"""Immutable export snapshots, grouped split and registered downloads."""

import hashlib
import json
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from ..core.config import DATA_ROOT
from ..database.store import connect


def new_destination(name, output_dir=None):
    base = (
        Path(output_dir).expanduser().resolve() if output_dir else DATA_ROOT / "exports"
    )
    safe = "".join(c for c in name if c.isalnum() or c in "-_")[:60] or "dataset"
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    dest = base / f"{safe}_{stamp}_{uuid.uuid4().hex[:8]}"
    dest.mkdir(parents=True, exist_ok=False)
    return dest


def split_groups(images, method="camera_day", val_fraction=0.2):
    if method not in ("camera_day", "image_hash"):
        raise ValueError("Split phải là camera_day hoặc image_hash.")
    if not 0 < val_fraction < 1:
        raise ValueError("Tỷ lệ validation phải lớn hơn 0 và nhỏ hơn 1.")
    groups = {}
    missing = 0
    for image in images:
        day = None
        if method == "camera_day" and image.get("timestamp"):
            try:
                day = datetime.fromisoformat(image["timestamp"]).date().isoformat()
            except ValueError:
                pass
        if day:
            group = image["camera_id"] + ":" + day
        else:
            group = "image:" + image["sha256"]
            missing += method == "camera_day"
        groups[image.get("id", image.get("image_id"))] = group
    # Identical frames retained for temporal analysis must not leak across
    # train/validation, even when captured on different days or cameras.
    parents = {group: group for group in groups.values()}

    def find(group):
        while parents[group] != group:
            parents[group] = parents[parents[group]]
            group = parents[group]
        return group

    seen_hashes = {}
    for image in images:
        iid = image.get("id", image.get("image_id"))
        group, digest = groups[iid], image["sha256"]
        if digest in seen_hashes:
            roots = sorted((find(group), find(seen_hashes[digest])))
            parents[roots[1]] = roots[0]
        else:
            seen_hashes[digest] = group
    original_count = len(parents)
    groups = {iid: find(group) for iid, group in groups.items()}
    unique = sorted(
        set(groups.values()), key=lambda s: hashlib.sha256(s.encode()).hexdigest()
    )
    warnings = []
    if len(unique) < original_count:
        warnings.append(
            "Đã gộp các nhóm chứa ảnh trùng SHA-256 để tránh trùng nội dung giữa train/val."
        )
    if len(unique) < 2:
        val = set()
        warnings.append(
            "Chỉ có một nhóm độc lập: tất cả ảnh vào train; cần thêm ngày/camera cho validation."
        )
    else:
        n = max(1, min(len(unique) - 1, round(len(unique) * val_fraction)))
        val = set(unique[:n])
    if missing:
        warnings.append(
            f"{missing} ảnh thiếu timestamp hợp lệ: dùng hash ảnh, chưa bảo đảm tránh rò rỉ các frame gần nhau."
        )
    if method == "image_hash":
        warnings.append(
            "Chia theo hash ảnh không ngăn rò rỉ giữa các frame cùng camera."
        )
    return (
        {iid: ("val" if group in val else "train") for iid, group in groups.items()},
        groups,
        warnings,
    )


def finish_export(dest, kind, summary):
    result = {"path": str(dest), "kind": kind, **summary}
    (dest / "export.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    archive = Path(shutil.make_archive(str(dest), "zip", dest.parent, dest.name))
    result["archive_bytes"] = archive.stat().st_size
    with connect() as db:
        eid = db.execute(
            "INSERT INTO exports(kind,path,summary) VALUES(?,?,?)",
            (kind, str(dest), json.dumps(result, ensure_ascii=False)),
        ).lastrowid
    return {**result, "export_id": eid, "download_url": f"/api/exports/{eid}/download"}
