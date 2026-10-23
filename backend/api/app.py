"""Local API. Run one process via launch.py; workspace coordination is in-process."""

import gc
import hashlib
import io
import json
import math
import os
import re
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from PIL import Image, ImageOps
from ..core.config import APP_ROOT, DATA_ROOT, DEFAULT_MODEL, CLASSES
from ..core.hardware import detect_runtime
from ..core.tasks import TaskManager, task_detail
from ..database.store import connect, init_db
from ..dataset.operations import import_folder, export_dataset, clear_dataset
from ..detection.models import ModelHub, ModelError
from ..pipeline.worker import JobRunner
from ..traffic import analysis as traffic

init_db()
runner = JobRunner()
tasks = TaskManager(runner)
app = FastAPI(title="AutoLabel AI Studio", version="0.4.1")


@app.middleware("http")
async def local_request_policy(request: Request, call_next):
    origin = request.headers.get("origin")
    if request.method not in ("GET", "HEAD", "OPTIONS") and origin:
        parsed = urlparse(origin)
        if parsed.netloc != request.headers.get("host") or parsed.scheme not in (
            "http",
            "https",
        ):
            return JSONResponse(
                {"detail": "Yêu cầu phải đến từ chính giao diện AutoLabel."},
                status_code=403,
            )
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "same-origin"
    response.headers["X-Frame-Options"] = "DENY"
    if "/thumbnail" not in request.url.path:
        response.headers["Cache-Control"] = "no-cache"
    return response


class ImportRequest(BaseModel):
    folder: str = Field(min_length=1)
    clear_first: bool = False
    keep_duplicates: bool = False
    background: bool = False


class StartRequest(BaseModel):
    yolo_model: str = Field(default_factory=lambda: str(DEFAULT_MODEL))
    device: Literal["auto", "cpu", "cuda", "mps"] = "auto"
    dino_model: str | None = None
    sam_model: str | None = None
    yolo_conf: float = Field(0.25, ge=0, le=1)
    imgsz: int = Field(960, ge=320, le=2048)
    mode: Literal["standard", "cpu_fast", "small_object", "high_accuracy"] = "standard"
    dino_box_threshold: float = Field(0.28, ge=0, le=1)
    dino_text_threshold: float = Field(0.25, ge=0, le=1)
    match_iou: float = Field(0.4, gt=0, le=1)
    analyze_traffic_after: bool = True
    auto_accept: bool = False
    accept_yolo_only: bool = False
    output_dir: str | None = None


class ReviewItem(BaseModel):
    id: int | None = None
    class_name: str
    box: list[float] = Field(min_length=4, max_length=4)
    accepted: bool = True
    metadata: dict | None = None


class ReviewRequest(BaseModel):
    annotations: list[ReviewItem] = Field(max_length=5000)
    expected_version: int = Field(ge=0)
    complete: bool = False
    negative: bool = False


class ExportRequest(BaseModel):
    name: str = "autolabel"
    output_dir: str | None = None
    include_pseudo: bool = False
    split_method: Literal["camera_day", "image_hash"] = "camera_day"
    val_fraction: float = Field(0.2, gt=0, lt=1)
    background: bool = False


class ROIRequest(BaseModel):
    config: dict


class TrafficLabelRequest(BaseModel):
    label: str
    accepted: bool = True


class TrafficExportRequest(BaseModel):
    name: str = "traffic"
    mode: str = "extended"
    background: bool = False


class ClassificationExportRequest(BaseModel):
    name: str = "traffic_classification"
    include_pseudo: bool = False
    background: bool = False


def operation(kind, fn, background=False):
    try:
        return tasks.run(kind, fn, background)
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc
    except (ValueError, OSError) as exc:
        raise HTTPException(400, str(exc)) from exc


def writable():
    if runner.maintenance:
        raise HTTPException(
            409, "Đang có tác vụ cập nhật dữ liệu; chờ hoàn tất rồi lưu lại."
        )


@app.get("/api/config")
def config():
    return {
        "version": "0.4.1",
        "classes": CLASSES,
        "traffic_classes": traffic.TRAFFIC_CLASSES,
        "workflow": ["dataset", "labeling", "review", "export"],
    }


@app.get("/api/health")
def health():
    result = detect_runtime()
    result.update(
        status="ok",
        version="0.4.1",
        workspace=str(DATA_ROOT),
        yolo_loaded=runner.hub.yolo_path,
        dino_loaded=runner.hub.dino_path,
        sam_loaded=runner.hub.sam_path,
        inference_device=runner.hub.device if runner.hub.yolo else result["device"],
        fallback_reason=runner.hub.fallback_reason,
        default_yolo=str(DEFAULT_MODEL),
        default_yolo_exists=DEFAULT_MODEL.is_file(),
        maintenance=runner.maintenance,
    )
    return result


@app.get("/api/model/check")
def model_check(
    path: str | None = None, device: Literal["auto", "cpu", "cuda", "mps"] = "auto"
):
    def check(progress):
        probe = ModelHub()
        try:
            return probe.load_yolo(path or str(DEFAULT_MODEL), device)
        except ModelError as exc:
            raise ValueError(str(exc)) from exc
        finally:
            probe.yolo = None
            gc.collect()

    return operation("model_check", check)


@app.post("/api/datasets/import")
def dataset_import(req: ImportRequest):
    return operation(
        "import",
        lambda p: import_folder(req.folder, req.clear_first, p, req.keep_duplicates),
        req.background,
    )


@app.post("/api/datasets/clear")
def dataset_clear():
    return operation("clear", lambda p: clear_dataset())


@app.get("/api/tasks/{task_id}")
def get_task(task_id: int):
    result = task_detail(task_id)
    if not result:
        raise HTTPException(404, "Không tìm thấy tác vụ.")
    return result


@app.get("/api/images")
def images(
    q: str = "",
    status: str = "all",
    review: str = "all",
    camera: str = "",
    limit: int = Query(60, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    where, args = [], []
    if status != "all":
        where.append("i.status=?")
        args.append(status)
    if review == "needs_review":
        where.append("i.review_state='unreviewed'")
    elif review == "high_risk":
        where.append(
            "EXISTS(SELECT 1 FROM annotations a WHERE a.image_id=i.id AND a.quality='high_risk' AND a.reviewed=0)"
        )
    elif review == "reviewed":
        where.append("i.review_state IN ('reviewed','negative')")
    elif review == "negative":
        where.append("i.review_state='negative'")
    elif review == "errors":
        where.append("i.error IS NOT NULL")
    if q:
        where.append("i.rel_path LIKE ?")
        args.append("%" + q + "%")
    if camera:
        where.append("i.camera_id=?")
        args.append(camera)
    clause = " WHERE " + " AND ".join(where) if where else ""
    with connect() as db:
        rows = db.execute(
            "SELECT i.*, (SELECT count(*) FROM annotations a WHERE a.image_id=i.id) object_count FROM images i"
            + clause
            + " ORDER BY i.id LIMIT ? OFFSET ?",
            (*args, limit, offset),
        ).fetchall()
        total = db.execute("SELECT count(*) FROM images i" + clause, args).fetchone()[0]
    return {
        "items": [dict(r) for r in rows],
        "total": total,
        "offset": offset,
        "limit": limit,
    }


def image_row(image_id):
    with connect() as db:
        row = db.execute("SELECT * FROM images WHERE id=?", (image_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Không tìm thấy ảnh.")
    if not Path(row["path"]).is_file():
        raise HTTPException(
            404, "Ảnh nguồn không còn tồn tại. Khôi phục ảnh về đường dẫn đã nhập."
        )
    return row


@app.get("/api/images/{image_id}/file")
def image_file(image_id: int):
    row = image_row(image_id)
    try:
        with Image.open(row["path"]) as source:
            if source.getexif().get(274, 1) != 1:
                buffer = io.BytesIO()
                ImageOps.exif_transpose(source).convert("RGB").save(
                    buffer, format="PNG"
                )
                return Response(buffer.getvalue(), media_type="image/png")
        return FileResponse(row["path"])
    except OSError as exc:
        raise HTTPException(400, "Không đọc được ảnh: " + str(exc)) from exc


@app.get("/api/images/{image_id}/thumbnail")
def thumbnail(image_id: int):
    row = image_row(image_id)
    stamp = Path(row["path"]).stat().st_mtime_ns
    key = hashlib.sha256(f'{row["sha256"]}:{stamp}'.encode()).hexdigest()
    cache = DATA_ROOT / "thumbnails"
    cache.mkdir(exist_ok=True, parents=True)
    target = cache / (key + ".jpg")
    if not target.exists():
        try:
            with Image.open(row["path"]) as source:
                im = ImageOps.exif_transpose(source).convert("RGB")
                im.thumbnail((320, 200))
                buffer = io.BytesIO()
                im.save(buffer, format="JPEG", quality=78)
            # Atomic replacement: concurrent thumbnail requests cannot see partial bytes.
            import uuid

            temp = cache / (key + "." + uuid.uuid4().hex + ".tmp")
            temp.write_bytes(buffer.getvalue())
            temp.replace(target)
        except OSError as exc:
            raise HTTPException(400, "Không đọc được ảnh thu nhỏ.") from exc
    return FileResponse(
        target,
        media_type="image/jpeg",
        headers={"Cache-Control": "private, max-age=300"},
    )


@app.get("/api/masks/{filename}")
def mask_file(filename: str):
    if not re.fullmatch(r"\d+_\d+\.png", filename):
        raise HTTPException(404, "Mask không hợp lệ.")
    path = DATA_ROOT / "masks" / filename
    if not path.is_file():
        raise HTTPException(404, "Không tìm thấy SAM mask.")
    return FileResponse(path, media_type="image/png")


@app.get("/api/images/{image_id}")
def image_detail(image_id: int):
    with connect() as db:
        db.execute("BEGIN")
        row = db.execute("SELECT * FROM images WHERE id=?", (image_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Không tìm thấy ảnh.")
        anns = []
        for item in db.execute(
            "SELECT * FROM annotations WHERE image_id=? ORDER BY id", (image_id,)
        ):
            value = dict(item)
            value["metadata"] = json.loads(value["metadata"] or "{}")
            anns.append(value)
    return {"image": dict(row), "annotations": anns}


@app.get("/api/images/{image_id}/history")
def history(image_id: int, limit: int = Query(50, ge=1, le=200)):
    with connect() as db:
        return {
            "items": [
                dict(r)
                for r in db.execute(
                    "SELECT * FROM annotation_history WHERE image_id=? ORDER BY id DESC LIMIT ?",
                    (image_id, limit),
                )
            ]
        }


@app.put("/api/images/{image_id}/annotations")
@app.put("/api/images/{image_id}/review")
def save_review(image_id: int, req: ReviewRequest):
    with runner.lock, connect() as db:
        writable()
        db.execute("BEGIN IMMEDIATE")
        im = db.execute("SELECT * FROM images WHERE id=?", (image_id,)).fetchone()
        if not im:
            raise HTTPException(404, "Không tìm thấy ảnh.")
        if im["status"] == "processing":
            raise HTTPException(
                409, "AI đang xử lý ảnh này. Chờ ảnh hoàn tất rồi tải lại."
            )
        if req.expected_version != im["review_version"]:
            raise HTTPException(
                409,
                "Ảnh đã được cập nhật ở tab khác hoặc bởi AI. Tải lại ảnh trước khi lưu; bản đang sửa chưa bị ghi đè.",
            )
        accepted = sum(item.accepted for item in req.annotations)
        if req.negative and (accepted or not req.complete):
            raise HTTPException(
                422,
                "Ảnh không có xe phải được duyệt hoàn tất và không có box được chấp nhận.",
            )
        if req.complete and not accepted and not req.negative:
            raise HTTPException(
                422, "Nếu ảnh không có xe, hãy bật xác nhận “Ảnh không có xe”."
            )
        identifiers = [item.id for item in req.annotations if item.id is not None]
        if len(identifiers) != len(set(identifiers)):
            raise HTTPException(422, "Annotation ID bị lặp.")
        current = {
            r["id"]: dict(r)
            for r in db.execute(
                "SELECT * FROM annotations WHERE image_id=?", (image_id,)
            )
        }
        keep = set()
        for item in req.annotations:
            name = item.class_name
            if name not in (*CLASSES, "ambiguous") or (
                name == "ambiguous" and item.accepted
            ):
                raise HTTPException(
                    422, "Class không hợp lệ hoặc ambiguous chưa được đổi lớp."
                )
            x1, y1, x2, y2 = item.box
            if not all(math.isfinite(v) for v in item.box) or not (
                0 <= x1 < x2 <= im["width"] and 0 <= y1 < y2 <= im["height"]
            ):
                raise HTTPException(
                    422, "Box phải nằm trong ảnh và có diện tích lớn hơn 0."
                )
            if item.id is not None and item.id not in current:
                raise HTTPException(409, "Annotation đã thay đổi; hãy tải lại ảnh.")
            before = current.get(item.id)
            metadata = json.loads(before["metadata"]) if before else {}
            if item.metadata is not None:
                metadata.update(item.metadata)
            if before:
                metadata.setdefault("original_source", before["source"])
                metadata.setdefault("original_quality", before["quality"])
            class_id = CLASSES.index(name) if name in CLASSES else -1
            quality = "human_reviewed" if item.accepted else "human_rejected"
            after = {
                "class_name": name,
                "box": item.box,
                "accepted": item.accepted,
                "metadata": metadata,
            }
            if before:
                aid = item.id
                keep.add(aid)
                db.execute(
                    "UPDATE annotations SET class_name=?,class_id=?,x1=?,y1=?,x2=?,y2=?,accepted=?,metadata=?,quality=?,reviewed=1,source='manual',version=version+1 WHERE id=?",
                    (
                        name,
                        class_id,
                        *item.box,
                        int(item.accepted),
                        json.dumps(metadata, ensure_ascii=False),
                        quality,
                        aid,
                    ),
                )
            else:
                aid = db.execute(
                    "INSERT INTO annotations(image_id,source,class_name,class_id,x1,y1,x2,y2,accepted,reviewed,quality,metadata) VALUES(?,'manual',?,?,?,?,?,?,?,1,?,?)",
                    (
                        image_id,
                        name,
                        class_id,
                        *item.box,
                        int(item.accepted),
                        quality,
                        json.dumps(metadata, ensure_ascii=False),
                    ),
                ).lastrowid
            db.execute(
                "INSERT INTO annotation_history(annotation_id,image_id,action,before_json,after_json) VALUES(?,?,?,?,?)",
                (
                    aid,
                    image_id,
                    "update" if before else "create",
                    json.dumps(before, ensure_ascii=False) if before else None,
                    json.dumps(after, ensure_ascii=False),
                ),
            )
        for aid, before in current.items():
            if aid not in keep:
                db.execute(
                    "INSERT INTO annotation_history(annotation_id,image_id,action,before_json) VALUES(?,?,?,?)",
                    (aid, image_id, "delete", json.dumps(before, ensure_ascii=False)),
                )
                db.execute("DELETE FROM annotations WHERE id=?", (aid,))
        state = (
            "negative" if req.negative else "reviewed" if req.complete else "unreviewed"
        )
        db.execute(
            "UPDATE images SET review_state=?,review_version=review_version+1,error=NULL,status=CASE WHEN ? THEN 'processed' ELSE status END WHERE id=?",
            (state, req.complete, image_id),
        )
        db.execute(
            "INSERT INTO annotation_history(image_id,action,after_json) VALUES(?,'review',?)",
            (
                image_id,
                json.dumps(
                    {"review_state": state, "version": im["review_version"] + 1}
                ),
            ),
        )
        existing = db.execute(
            "SELECT features_json FROM traffic_measurements WHERE image_id=?",
            (image_id,),
        ).fetchone()
        if existing:
            features = json.loads(existing[0])
            features["features_stale"] = True
            db.execute(
                "UPDATE traffic_measurements SET features_json=? WHERE image_id=?",
                (json.dumps(features, ensure_ascii=False), image_id),
            )
    return {
        "saved": True,
        "count": len(req.annotations),
        "review_state": state,
        "version": im["review_version"] + 1,
    }


@app.get("/api/stats")
def stats():
    with connect() as db:
        statuses = {
            r["status"]: r["n"]
            for r in db.execute("SELECT status,count(*) n FROM images GROUP BY status")
        }
        states = {
            r["review_state"]: r["n"]
            for r in db.execute(
                "SELECT review_state,count(*) n FROM images GROUP BY review_state"
            )
        }
        classes = {
            r["class_name"]: r["n"]
            for r in db.execute(
                "SELECT class_name,count(*) n FROM annotations WHERE accepted=1 GROUP BY class_name"
            )
        }
        quality = {
            r["quality"]: r["n"]
            for r in db.execute(
                "SELECT quality,count(*) n FROM annotations WHERE reviewed=0 GROUP BY quality"
            )
        }
        last = db.execute("SELECT * FROM jobs ORDER BY id DESC LIMIT 1").fetchone()
        job = dict(last) if last else None
        if job:
            timing = db.execute(
                "SELECT avg(duration) mean FROM job_items WHERE job_id=? AND state='processed' AND duration IS NOT NULL",
                (job["id"],),
            ).fetchone()[0]
            done = job["processed"] + job["failed"]
            job.update(
                percent=round(100 * done / job["total"], 1) if job["total"] else 0,
                seconds_per_image=timing,
                eta_seconds=(
                    round(max(0, job["total"] - done) * timing) if timing else None
                ),
                worker_alive=runner.busy(),
            )
            job.pop("config", None)
        traffic_count = db.execute(
            "SELECT count(*) FROM traffic_measurements WHERE review_status='accepted'"
        ).fetchone()[0]
        errors = db.execute(
            "SELECT count(*) FROM images WHERE error IS NOT NULL"
        ).fetchone()[0]
        samples = [
            dict(r)
            for r in db.execute(
                "SELECT id,rel_path,review_state,status,object_count FROM (SELECT i.*,(SELECT count(*) FROM annotations a WHERE a.image_id=i.id) object_count FROM images i ORDER BY id DESC LIMIT 6)"
            )
        ]
    return {
        "images": sum(statuses.values()),
        "statuses": statuses,
        "review_states": states,
        "objects": sum(classes.values()),
        "classes": classes,
        "quality": quality,
        "reviewed_images": states.get("reviewed", 0) + states.get("negative", 0),
        "traffic_verified": traffic_count,
        "errors": errors,
        "job": job,
        "task": task_detail(),
        "recent_images": samples,
    }


@app.post("/api/jobs/start")
def job_start(req: StartRequest):
    cfg = req.model_dump()
    if not Path(cfg["yolo_model"]).expanduser().is_file():
        raise HTTPException(
            400,
            "Không tìm thấy checkpoint. Nhập đường dẫn best.pt trên máy chạy server.",
        )
    for key in ("dino_model", "sam_model"):
        if cfg[key] and not Path(cfg[key]).expanduser().is_dir():
            raise HTTPException(400, "Thư mục model tùy chọn không tồn tại: " + key)
    try:
        return {"job_id": runner.start(cfg), "state": "running"}
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc


@app.post("/api/jobs/{action}")
def job_action(action: Literal["pause", "resume", "stop", "cancel"]):
    try:
        getattr(runner, action)()
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc
    return stats()["job"]


@app.get("/api/logs")
def logs(limit: int = Query(100, ge=1, le=500), level: str = "all"):
    clause = " WHERE level=?" if level != "all" else ""
    args = (level, limit) if level != "all" else (limit,)
    with connect() as db:
        return {
            "items": [
                dict(r)
                for r in db.execute(
                    "SELECT * FROM events" + clause + " ORDER BY id DESC LIMIT ?", args
                )
            ]
        }


@app.post("/api/export")
def do_export(req: ExportRequest):
    return operation(
        "export_detection",
        lambda p: export_dataset(
            req.name,
            req.output_dir,
            req.include_pseudo,
            req.split_method,
            req.val_fraction,
            p,
        ),
        req.background,
    )


@app.get("/api/exports")
def export_history():
    with connect() as db:
        rows = [
            dict(r)
            for r in db.execute("SELECT * FROM exports ORDER BY id DESC LIMIT 100")
        ]
    for row in rows:
        row["summary"] = json.loads(row["summary"])
        row["download_url"] = f'/api/exports/{row["id"]}/download'
    return {"items": rows}


@app.get("/api/exports/{export_id}/download")
def export_download(export_id: int):
    with connect() as db:
        row = db.execute("SELECT path FROM exports WHERE id=?", (export_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Không tìm thấy bản xuất.")
    archive = Path(row["path"] + ".zip")
    if not archive.is_file():
        raise HTTPException(404, "Tệp ZIP đã được di chuyển hoặc xóa.")
    return FileResponse(archive, media_type="application/zip", filename=archive.name)


@app.get("/api/cameras")
def list_cameras():
    return traffic.cameras()


@app.get("/api/cameras/{camera_id}/roi")
def read_roi(camera_id: str):
    return traffic.get_roi(camera_id) or {
        "rois": [],
        "calibration": {},
        "calibration_confirmed": False,
    }


@app.put("/api/cameras/{camera_id}/roi")
def write_roi(camera_id: str, req: ROIRequest):
    with runner.lock:
        writable()
        try:
            return traffic.save_roi(camera_id, req.config)
        except (ValueError, TypeError, KeyError) as exc:
            raise HTTPException(422, str(exc)) from exc


@app.post("/api/traffic/analyze")
def analyze_traffic(background: bool = False):
    return operation("traffic_analysis", traffic.analyze_all, background)


@app.get("/api/traffic/labels")
def traffic_labels(
    limit: int = Query(60, ge=1, le=500),
    offset: int = Query(0, ge=0),
    review_only: bool = False,
    q: str = "",
    camera: str = "",
):
    rows = traffic.list_labels(limit, review_only, offset, q, camera)
    with connect() as db:
        where, args = [], []
        if review_only:
            where.append("t.review_status NOT IN ('accepted','rejected')")
        if q:
            where.append("i.rel_path LIKE ?")
            args.append("%" + q + "%")
        if camera:
            where.append("t.camera_id=?")
            args.append(camera)
        total = db.execute(
            "SELECT count(*) FROM traffic_measurements t JOIN images i ON i.id=t.image_id"
            + (" WHERE " + " AND ".join(where) if where else ""),
            args,
        ).fetchone()[0]
    for row in rows:
        row["features"] = json.loads(row.pop("features_json"))
    return {"items": rows, "total": total, "offset": offset}


@app.put("/api/traffic/labels/{image_id}")
def review_traffic(image_id: int, req: TrafficLabelRequest):
    with runner.lock:
        writable()
        try:
            return traffic.set_label(image_id, req.label, req.accepted)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc


@app.post("/api/traffic/export-classification")
def export_classification(req: ClassificationExportRequest):
    return operation(
        "export_classification",
        lambda p: traffic.export_classification(req.name, req.include_pseudo, p),
        req.background,
    )


@app.get("/api/traffic/temporal")
def temporal(limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0)):
    try:
        rows = traffic.temporal_records()
        return {"items": rows[offset : offset + limit], "total": len(rows)}
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@app.post("/api/traffic/export")
def export_temporal(req: TrafficExportRequest):
    return operation(
        "export_temporal",
        lambda p: traffic.export_traffic(req.name, req.mode, p),
        req.background,
    )


app.mount("/", StaticFiles(directory=APP_ROOT / "frontend", html=True), name="frontend")
