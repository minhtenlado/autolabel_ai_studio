"""SQLite storage and additive, backed-up migrations."""

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from ..core.config import DATA_ROOT, DB_PATH

SCHEMA_VERSION = 4
SCHEMA = """
CREATE TABLE IF NOT EXISTS workspace_meta(key TEXT PRIMARY KEY,value INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS images(
 id INTEGER PRIMARY KEY, path TEXT NOT NULL UNIQUE, rel_path TEXT NOT NULL,
 sha256 TEXT NOT NULL, width INTEGER, height INTEGER, status TEXT NOT NULL DEFAULT 'pending',
 error TEXT, imported_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, processed_at TEXT,
 camera_id TEXT NOT NULL DEFAULT 'default', timestamp TEXT,
 review_state TEXT NOT NULL DEFAULT 'unreviewed', review_version INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_images_status ON images(status);
CREATE INDEX IF NOT EXISTS idx_images_sha256 ON images(sha256);
CREATE TABLE IF NOT EXISTS jobs(
 id INTEGER PRIMARY KEY, state TEXT NOT NULL, config TEXT NOT NULL,
 total INTEGER NOT NULL DEFAULT 0, processed INTEGER NOT NULL DEFAULT 0,
 failed INTEGER NOT NULL DEFAULT 0, current_path TEXT, error TEXT,
 started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS job_items(
 job_id INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
 image_id INTEGER NOT NULL REFERENCES images(id) ON DELETE CASCADE,
 state TEXT NOT NULL DEFAULT 'pending', error TEXT, duration REAL,
 PRIMARY KEY(job_id,image_id)
);
CREATE TABLE IF NOT EXISTS annotations(
 id INTEGER PRIMARY KEY, image_id INTEGER NOT NULL REFERENCES images(id) ON DELETE CASCADE,
 source TEXT NOT NULL, class_name TEXT NOT NULL, class_id INTEGER NOT NULL,
 x1 REAL NOT NULL,y1 REAL NOT NULL,x2 REAL NOT NULL,y2 REAL NOT NULL,
 score REAL, quality TEXT, heuristic_score REAL, reviewed INTEGER NOT NULL DEFAULT 0,
 accepted INTEGER NOT NULL DEFAULT 1, metadata TEXT NOT NULL DEFAULT '{}', version INTEGER NOT NULL DEFAULT 1,
 created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_ann_image ON annotations(image_id);
CREATE TABLE IF NOT EXISTS camera_configs(camera_id TEXT PRIMARY KEY,config TEXT NOT NULL,updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS traffic_measurements(image_id INTEGER PRIMARY KEY REFERENCES images(id) ON DELETE CASCADE,camera_id TEXT NOT NULL,timestamp TEXT,features_json TEXT NOT NULL,predicted_class TEXT,quality TEXT,review_status TEXT NOT NULL DEFAULT 'needs_review',updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE INDEX IF NOT EXISTS idx_traffic_time ON traffic_measurements(camera_id,timestamp);
CREATE TABLE IF NOT EXISTS annotation_history(
 id INTEGER PRIMARY KEY, annotation_id INTEGER, image_id INTEGER NOT NULL,
 action TEXT NOT NULL, before_json TEXT, after_json TEXT, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_history_image ON annotation_history(image_id);
CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY, image_id INTEGER, level TEXT, message TEXT, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS tasks(
 id INTEGER PRIMARY KEY, kind TEXT NOT NULL, state TEXT NOT NULL,
 completed INTEGER NOT NULL DEFAULT 0, total INTEGER NOT NULL DEFAULT 0,
 message TEXT, result TEXT, error TEXT,
 started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS exports(
 id INTEGER PRIMARY KEY, kind TEXT NOT NULL, path TEXT NOT NULL UNIQUE,
 summary TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""


@contextmanager
def connect():
    DATA_ROOT.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB_PATH, timeout=30)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def init_db():
    with connect() as db:
        old = db.execute("PRAGMA user_version").fetchone()[0]
        exists = db.execute(
            "SELECT 1 FROM sqlite_master WHERE name='images'"
        ).fetchone()
        if old > SCHEMA_VERSION:
            raise RuntimeError(
                "Database được tạo bởi phiên bản mới hơn; không được hạ cấp ứng dụng."
            )
        if exists and old < SCHEMA_VERSION:
            backup_dir = DATA_ROOT / "backups"
            backup_dir.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
            with sqlite3.connect(backup_dir / f"pre-v04-{stamp}.sqlite3") as backup:
                db.backup(backup)
        db.execute("PRAGMA journal_mode=WAL")
        db.executescript(SCHEMA)
        columns = {r["name"] for r in db.execute("PRAGMA table_info(images)")}
        for name, definition in {
            "camera_id": "TEXT NOT NULL DEFAULT 'default'",
            "timestamp": "TEXT",
            "review_state": "TEXT NOT NULL DEFAULT 'unreviewed'",
            "review_version": "INTEGER NOT NULL DEFAULT 0",
        }.items():
            if name not in columns:
                db.execute(f"ALTER TABLE images ADD COLUMN {name} {definition}")
        db.execute(
            "CREATE INDEX IF NOT EXISTS idx_images_review ON images(review_state)"
        )
        db.execute("CREATE INDEX IF NOT EXISTS idx_images_camera ON images(camera_id)")
        # Repair the old manual-label JSON mismatch without inventing verification.
        if old < SCHEMA_VERSION:
            for row in db.execute(
                "SELECT * FROM traffic_measurements WHERE quality='human_verified'"
            ).fetchall():
                try:
                    data = json.loads(row["features_json"])
                    data.update(
                        predicted_traffic_class=row["predicted_class"],
                        review_status=row["review_status"],
                        label_source="human_verified",
                        verified_by_human=True,
                    )
                    names = ["Thong_thoang", "Dong_xe", "Un_u_nhe", "Un_tac_nang"]
                    data["class_id"] = (
                        names.index(row["predicted_class"])
                        if row["predicted_class"] in names
                        else None
                    )
                    db.execute(
                        "UPDATE traffic_measurements SET features_json=? WHERE image_id=?",
                        (json.dumps(data, ensure_ascii=False), row["image_id"]),
                    )
                except (ValueError, TypeError):
                    pass
        db.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
        db.execute(
            "UPDATE jobs SET state=CASE WHEN state='stopping' THEN 'stopped' WHEN state='cancelling' THEN 'cancelled' ELSE 'paused' END,updated_at=CURRENT_TIMESTAMP WHERE state IN ('running','pausing','stopping','cancelling')"
        )
        db.execute("UPDATE job_items SET state='pending' WHERE state='processing'")
        db.execute(
            "UPDATE images SET status='pending',error=NULL WHERE status='processing'"
        )
        db.execute(
            "UPDATE tasks SET state='interrupted',error='Ứng dụng đã khởi động lại; hãy chạy lại thao tác.',updated_at=CURRENT_TIMESTAMP WHERE state='running'"
        )
