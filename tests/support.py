"""Test isolation: never initialize or migrate the user's actual workspace."""

import importlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image
from backend.database import store
from backend.core import config

with tempfile.TemporaryDirectory() as initial:
    with patch.object(store, "DATA_ROOT", Path(initial)), patch.object(
        store, "DB_PATH", Path(initial) / "init.sqlite3"
    ), patch.object(config, "DATA_ROOT", Path(initial)):
        api_module = importlib.import_module("backend.api.app")
from fastapi.testclient import TestClient
from backend.dataset import operations, exports
from backend.pipeline import worker
from backend.core.tasks import TaskManager


class StudioTestCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.data = self.root / "workspace"
        self.patchers = [
            patch.object(store, "DATA_ROOT", self.data),
            patch.object(store, "DB_PATH", self.data / "test.sqlite3"),
        ]
        for module in (operations, exports, worker, api_module):
            self.patchers.append(patch.object(module, "DATA_ROOT", self.data))
        self.runner = worker.JobRunner()
        self.patchers.extend(
            [
                patch.object(api_module, "runner", self.runner),
                patch.object(api_module, "tasks", TaskManager(self.runner)),
            ]
        )
        for patcher in self.patchers:
            patcher.start()
        store.init_db()
        self.client = TestClient(api_module.app)

    def tearDown(self):
        if self.runner.busy():
            self.runner.stop_event.set()
            self.runner.pause_event.clear()
            self.runner.thread.join(10)
        task = api_module.tasks.thread
        if task and task.is_alive():
            task.join(10)
        self.client.close()
        for patcher in reversed(self.patchers):
            patcher.stop()
        self.temp.cleanup()

    def add_image(
        self, name="cam_a/20261022_120000.png", color="red", status="pending"
    ):
        target = self.root / "images" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (100, 80), color).save(target)
        import hashlib

        digest = hashlib.sha256(target.read_bytes()).hexdigest()
        with store.connect() as db:
            return db.execute(
                "INSERT INTO images(path,rel_path,sha256,width,height,camera_id,timestamp,status) VALUES(?,?,?,?,?,?,?,?)",
                (
                    str(target),
                    name,
                    digest,
                    100,
                    80,
                    name.split("/")[0],
                    "2026-10-22 12:00:00",
                    status,
                ),
            ).lastrowid

    def add_box(
        self,
        iid,
        source="yolo_only",
        accepted=0,
        reviewed=0,
        quality="needs_review",
        metadata="{}",
    ):
        with store.connect() as db:
            return db.execute(
                "INSERT INTO annotations(image_id,source,class_name,class_id,x1,y1,x2,y2,accepted,reviewed,quality,metadata) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    iid,
                    source,
                    "car",
                    1,
                    10,
                    10,
                    30,
                    30,
                    accepted,
                    reviewed,
                    quality,
                    metadata,
                ),
            ).lastrowid

    def review(self, iid, annotations=None, **kw):
        return self.client.put(
            f"/api/images/{iid}/review",
            json={"expected_version": 0, "annotations": annotations or [], **kw},
        )
