"""One inference worker with a durable, fixed job manifest."""

import json
import threading
import time
from pathlib import Path
from PIL import Image, ImageOps
from ..database.store import connect
from ..detection.models import ModelHub
from ..consensus.engine import match_and_score
from ..core.config import CLASSES, DATA_ROOT
from ..dataset.operations import copy_image


class JobRunner:
    def __init__(self):
        self.hub = ModelHub()
        self.thread = None
        self.job_id = None
        self.pause_event = threading.Event()
        self.stop_event = threading.Event()
        self.lock = threading.RLock()
        self.maintenance = False
        self.stop_target = "stopped"

    def busy(self):
        return bool(self.thread and self.thread.is_alive())

    @staticmethod
    def _counts(db, job_id):
        counts = {
            r["state"]: r["n"]
            for r in db.execute(
                "SELECT state,count(*) n FROM job_items WHERE job_id=? GROUP BY state",
                (job_id,),
            )
        }
        db.execute(
            "UPDATE jobs SET total=?,processed=?,failed=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (
                sum(counts.values()),
                counts.get("processed", 0),
                counts.get("failed", 0),
                job_id,
            ),
        )

    def start(self, config, resume=False):
        with self.lock:
            if self.busy() or self.maintenance:
                raise RuntimeError(
                    "Đang có tác vụ. Chờ kết thúc trước khi chạy job mới."
                )
            with connect() as db:
                if resume:
                    job = db.execute(
                        "SELECT * FROM jobs ORDER BY id DESC LIMIT 1"
                    ).fetchone()
                    if not job or job["state"] not in (
                        "paused",
                        "stopped",
                        "failed",
                        "completed_with_errors",
                    ):
                        raise RuntimeError(
                            "Không có job đang tạm dừng/dừng/lỗi để tiếp tục."
                        )
                    job_id = job["id"]
                    config = json.loads(job["config"])
                    # Migration of an old job without items: reconstruct only unfinished work.
                    if not db.execute(
                        "SELECT 1 FROM job_items WHERE job_id=?", (job_id,)
                    ).fetchone():
                        db.execute(
                            "INSERT INTO job_items(job_id,image_id) SELECT ?,id FROM images WHERE status!='processed' AND review_state='unreviewed'",
                            (job_id,),
                        )
                    db.execute(
                        "UPDATE job_items SET state='pending',error=NULL WHERE job_id=? AND state IN ('failed','processing')",
                        (job_id,),
                    )
                else:
                    ids = [
                        r[0]
                        for r in db.execute(
                            "SELECT i.id FROM images i WHERE status IN ('pending','failed') AND review_state='unreviewed' AND NOT EXISTS(SELECT 1 FROM annotations a WHERE a.image_id=i.id AND (a.reviewed=1 OR a.source IN ('original','manual'))) ORDER BY i.id"
                        )
                    ]
                    if not ids:
                        raise RuntimeError(
                            "Không có ảnh chưa xử lý. Nhập thêm ảnh hoặc kiểm tra bộ lọc lỗi."
                        )
                    job_id = db.execute(
                        "INSERT INTO jobs(state,config) VALUES('running',?)",
                        (json.dumps(config),),
                    ).lastrowid
                    db.executemany(
                        "INSERT INTO job_items(job_id,image_id) VALUES(?,?)",
                        [(job_id, iid) for iid in ids],
                    )
                remaining = db.execute(
                    "SELECT count(*) FROM job_items WHERE job_id=? AND state='pending'",
                    (job_id,),
                ).fetchone()[0]
                if not remaining and not (
                    resume and config.get("analyze_traffic_after")
                ):
                    raise RuntimeError(
                        "Job đã xử lý hết ảnh; không có ảnh cần tiếp tục."
                    )
                db.execute(
                    "UPDATE images SET status='pending',error=NULL WHERE id IN (SELECT image_id FROM job_items WHERE job_id=? AND state='pending')",
                    (job_id,),
                )
                db.execute(
                    "UPDATE jobs SET state='running',error=NULL,current_path=NULL,updated_at=CURRENT_TIMESTAMP WHERE id=?",
                    (job_id,),
                )
                self._counts(db, job_id)
            self.job_id = job_id
            self.pause_event.clear()
            self.stop_event.clear()
            self.stop_target = "stopped"
            self.thread = threading.Thread(
                target=self._run,
                args=(job_id, config),
                daemon=True,
                name="autolabel-job",
            )
            self.thread.start()
            return job_id

    def pause(self):
        with self.lock:
            if not self.busy() or self.stop_event.is_set():
                raise RuntimeError("Không có job đang chạy để tạm dừng.")
            self.pause_event.set()
            with connect() as db:
                db.execute(
                    "UPDATE jobs SET state='pausing',updated_at=CURRENT_TIMESTAMP WHERE id=?",
                    (self.job_id,),
                )

    def resume(self):
        with self.lock:
            if not self.busy():
                return self.start({}, resume=True)
            if self.stop_event.is_set():
                raise RuntimeError(
                    "Đang kết thúc ảnh hiện tại. Chờ job dừng rồi tiếp tục."
                )
            if not self.pause_event.is_set():
                raise RuntimeError("Job đang chạy, không cần tiếp tục.")
            self.pause_event.clear()
            with connect() as db:
                db.execute(
                    "UPDATE jobs SET state='running',updated_at=CURRENT_TIMESTAMP WHERE id=?",
                    (self.job_id,),
                )
            return self.job_id

    def _request_stop(self, target):
        with self.lock:
            if not self.busy():
                raise RuntimeError("Không có worker đang chạy.")
            self.stop_target = target
            self.stop_event.set()
            self.pause_event.clear()
            with connect() as db:
                db.execute(
                    "UPDATE jobs SET state=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",
                    ("stopping" if target == "stopped" else "cancelling", self.job_id),
                )

    def stop(self):
        self._request_stop("stopped")

    def cancel(self):
        self._request_stop("cancelled")

    def _checkpoint(self, job_id):
        while self.pause_event.is_set() and not self.stop_event.is_set():
            with self.lock, connect() as db:
                if self.pause_event.is_set() and not self.stop_event.is_set():
                    db.execute(
                        "UPDATE jobs SET state='paused',updated_at=CURRENT_TIMESTAMP WHERE id=?",
                        (job_id,),
                    )
            self.stop_event.wait(0.15)
        return not self.stop_event.is_set()

    def _run(self, job_id, config):
        try:
            # Release optional models from the preceding job before loading a new one.
            self.hub.dino = self.hub.dino_processor = self.hub.dino_path = None
            self.hub.sam = self.hub.sam_processor = self.hub.sam_path = None
            self.hub.load_yolo(config["yolo_model"], config.get("device", "auto"))
            if not self._checkpoint(job_id):
                return
            if config.get("dino_model"):
                self.hub.load_dino(config["dino_model"])
            if config.get("sam_model"):
                self.hub.load_sam(config["sam_model"])
            with connect() as db:
                ids = [
                    r[0]
                    for r in db.execute(
                        "SELECT image_id FROM job_items WHERE job_id=? AND state='pending' ORDER BY image_id",
                        (job_id,),
                    )
                ]
            for iid in ids:
                if not self._checkpoint(job_id):
                    break
                with self.lock, connect() as db:
                    row = db.execute(
                        "SELECT * FROM images WHERE id=?", (iid,)
                    ).fetchone()
                    if not row:
                        continue
                    protected = db.execute(
                        "SELECT 1 FROM annotations WHERE image_id=? AND (reviewed=1 OR source IN ('original','manual')) LIMIT 1",
                        (iid,),
                    ).fetchone()
                    if row["review_state"] != "unreviewed" or protected:
                        db.execute(
                            "UPDATE job_items SET state='processed' WHERE job_id=? AND image_id=?",
                            (job_id, iid),
                        )
                        self._counts(db, job_id)
                        continue
                    db.execute(
                        "UPDATE jobs SET current_path=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",
                        (row["rel_path"], job_id),
                    )
                    db.execute(
                        "UPDATE images SET status='processing',error=NULL WHERE id=?",
                        (iid,),
                    )
                    db.execute(
                        "UPDATE job_items SET state='processing' WHERE job_id=? AND image_id=?",
                        (job_id, iid),
                    )
                start = time.monotonic()
                try:
                    with Image.open(row["path"]) as source:
                        image = ImageOps.exif_transpose(source).convert("RGB")
                    yd = self.hub.yolo_predict(
                        image,
                        config.get("yolo_conf", 0.25),
                        config.get("imgsz", 960),
                        config.get("mode", "standard"),
                    )
                    errors = []
                    try:
                        dd = (
                            self.hub.dino_predict(
                                image,
                                config.get("dino_box_threshold", 0.28),
                                config.get("dino_text_threshold", 0.25),
                            )
                            if self.hub.dino
                            else []
                        )
                    except Exception as exc:
                        dd = []
                        errors.append("DINO: " + str(exc)[:400])
                    final = match_and_score(
                        yd, dd, *image.size, config.get("match_iou", 0.4)
                    )
                    for item in final:
                        item["image_id"] = iid
                        item["metadata"]["job_id"] = job_id
                        item["metadata"]["model_path"] = self.hub.yolo_path
                        item["accepted"] = bool(
                            item["quality"] == "high_agreement"
                            and config.get("auto_accept")
                        )
                        if (
                            item["source"] == "yolo_only"
                            and not self.hub.dino
                            and config.get("accept_yolo_only")
                            and not item["metadata"].get("warnings")
                        ):
                            item["accepted"] = True
                            item["metadata"][
                                "acceptance_policy"
                            ] = "unverified_yolo_only_opt_in"
                    if self.hub.sam and final:
                        try:
                            self.hub.sam_refine(image, final, DATA_ROOT / "masks")
                        except Exception as exc:
                            errors.append("SAM: " + str(exc)[:400])
                    with self.lock, connect() as db:
                        db.execute(
                            "DELETE FROM annotations WHERE image_id=? AND reviewed=0 AND source NOT IN ('original','manual')",
                            (iid,),
                        )
                        for item in final:
                            name = item["class_name"]
                            if name not in (*CLASSES, "ambiguous"):
                                continue
                            db.execute(
                                "INSERT INTO annotations(image_id,source,class_name,class_id,x1,y1,x2,y2,score,quality,heuristic_score,accepted,metadata) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                                (
                                    iid,
                                    item["source"],
                                    name,
                                    CLASSES.index(name) if name in CLASSES else -1,
                                    *item["box"],
                                    item["score"],
                                    item["quality"],
                                    item["heuristic_score"],
                                    int(item["accepted"]),
                                    json.dumps(item["metadata"], ensure_ascii=False),
                                ),
                            )
                        db.execute(
                            "UPDATE images SET status='processed',processed_at=CURRENT_TIMESTAMP,error=NULL,review_version=review_version+1 WHERE id=?",
                            (iid,),
                        )
                        db.execute(
                            "UPDATE job_items SET state='processed',duration=? WHERE job_id=? AND image_id=?",
                            (time.monotonic() - start, job_id, iid),
                        )
                        self._counts(db, job_id)
                        db.execute(
                            "INSERT INTO events(image_id,level,message) VALUES(?,'info',?)",
                            (
                                iid,
                                f"Đã xử lý {len(final)} nhãn trong {time.monotonic()-start:.2f}s",
                            ),
                        )
                        for error in errors:
                            db.execute(
                                "INSERT INTO events(image_id,level,message) VALUES(?,'warning',?)",
                                (iid, error),
                            )
                    if config.get("output_dir"):
                        self._save_proposals(
                            job_id, config["output_dir"], dict(row), final
                        )
                except Exception as exc:
                    with connect() as db:
                        db.execute(
                            "UPDATE images SET status='failed',error=? WHERE id=?",
                            (str(exc)[:1500], iid),
                        )
                        db.execute(
                            "UPDATE job_items SET state='failed',error=? WHERE job_id=? AND image_id=?",
                            (str(exc)[:1500], job_id, iid),
                        )
                        self._counts(db, job_id)
                        db.execute(
                            "INSERT INTO events(image_id,level,message) VALUES(?,'error',?)",
                            (iid, str(exc)[:1500]),
                        )
            if (
                config.get("analyze_traffic_after", False)
                and not self.stop_event.is_set()
            ):
                from ..traffic.analysis import analyze_all

                try:
                    with self.lock:
                        self.maintenance = True
                    with connect() as db:
                        db.execute(
                            "UPDATE jobs SET current_path=? WHERE id=?",
                            ("Đang cập nhật đặc trưng traffic…", job_id),
                        )
                    result = analyze_all(checkpoint=lambda: self._checkpoint(job_id))
                    with connect() as db:
                        db.execute(
                            "INSERT INTO events(level,message) VALUES('info',?)",
                            (
                                f"Traffic: đã cập nhật {result['processed']} ảnh; nhãn theo luật cần kiểm duyệt.",
                            ),
                        )
                except Exception as exc:
                    with connect() as db:
                        db.execute(
                            "INSERT INTO events(level,message) VALUES('warning',?)",
                            ("Traffic sau detection: " + str(exc)[:1000],),
                        )
                finally:
                    with self.lock:
                        self.maintenance = False
        except Exception as exc:
            with connect() as db:
                db.execute(
                    "UPDATE jobs SET state='failed',error=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",
                    (str(exc)[:1500], job_id),
                )
        finally:
            with self.lock, connect() as db:
                row = db.execute(
                    "SELECT state,failed FROM jobs WHERE id=?", (job_id,)
                ).fetchone()
                if row:
                    state = (
                        self.stop_target
                        if self.stop_event.is_set()
                        else (
                            "failed"
                            if row["state"] == "failed"
                            else (
                                "completed_with_errors"
                                if row["failed"]
                                else "completed"
                            )
                        )
                    )
                    db.execute(
                        "UPDATE jobs SET state=?,current_path=NULL,updated_at=CURRENT_TIMESTAMP WHERE id=?",
                        (state, job_id),
                    )

    def _save_proposals(self, job_id, output_dir, row, final):
        try:
            dest = Path(output_dir).expanduser().resolve() / f"job_{job_id}"
            (dest / "proposals").mkdir(parents=True, exist_ok=True)
            (dest / "images").mkdir(exist_ok=True)
            filename = f"{row['id']:08d}_{Path(row['path']).name}"
            copy_image(row["path"], dest / "images" / filename)
            payload = {
                "image": filename,
                "image_id": row["id"],
                "review_required": True,
                "annotations": final,
            }
            target = dest / "proposals" / f"{row['id']:08d}.json"
            temporary = target.with_suffix(".tmp")
            temporary.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            temporary.replace(target)
            (dest / "README.txt").write_text(
                "Checkpoint proposals only. Unreviewed images are NOT negative examples.\nUse the application Export page after review to create YOLO training data.\n",
                encoding="utf-8",
            )
        except Exception as exc:
            with connect() as db:
                db.execute(
                    "INSERT INTO events(image_id,level,message) VALUES(?,'warning',?)",
                    (row["id"], "Không lưu được proposal: " + str(exc)[:1000]),
                )
