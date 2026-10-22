import sqlite3
from contextlib import contextmanager
from ..core.config import DATA_ROOT, DB_PATH

SCHEMA = '''
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS images(
 id INTEGER PRIMARY KEY, path TEXT NOT NULL UNIQUE, rel_path TEXT NOT NULL,
 sha256 TEXT NOT NULL, width INTEGER, height INTEGER, status TEXT NOT NULL DEFAULT 'pending',
 error TEXT, imported_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, processed_at TEXT, camera_id TEXT NOT NULL DEFAULT 'default', timestamp TEXT
);
CREATE INDEX IF NOT EXISTS idx_images_status ON images(status);
CREATE INDEX IF NOT EXISTS idx_images_sha256 ON images(sha256);
CREATE INDEX IF NOT EXISTS idx_images_path ON images(path);
CREATE TABLE IF NOT EXISTS jobs(
 id INTEGER PRIMARY KEY, state TEXT NOT NULL, config TEXT NOT NULL,
 total INTEGER NOT NULL DEFAULT 0, processed INTEGER NOT NULL DEFAULT 0,
 failed INTEGER NOT NULL DEFAULT 0, current_path TEXT, error TEXT,
 started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
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
CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY, image_id INTEGER, level TEXT, message TEXT, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
'''

@contextmanager
def connect():
    DATA_ROOT.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB_PATH, timeout=30)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA foreign_keys=ON')
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
        db.executescript(SCHEMA)
        for statement in ("ALTER TABLE images ADD COLUMN camera_id TEXT NOT NULL DEFAULT 'default'", "ALTER TABLE images ADD COLUMN timestamp TEXT"):
            try: db.execute(statement)
            except sqlite3.OperationalError: pass
        db.execute("UPDATE jobs SET state='paused',updated_at=CURRENT_TIMESTAMP WHERE state='running'")
        db.execute("UPDATE images SET status='pending',error=NULL WHERE status='processing'")
