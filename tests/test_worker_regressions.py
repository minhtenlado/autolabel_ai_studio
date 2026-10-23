import json
import threading
import time
from pathlib import Path
from backend.consensus.engine import Detection, match_and_score
from backend.database import store
from backend.pipeline.worker import JobRunner
from support import StudioTestCase


class FakeHub:
    def __init__(self, gate=False, fail_first=False):
        self.yolo = None
        self.yolo_path = None
        self.dino = None
        self.dino_path = None
        self.sam = None
        self.sam_path = None
        self.device = "cpu"
        self.fallback_reason = None
        self.calls = 0
        self.gate = gate
        self.fail_first = fail_first
        self.entered = threading.Event()
        self.release = threading.Event()

    def load_yolo(self, path, device):
        self.yolo_path = path
        self.yolo = object()
        return {"device": "cpu"}

    def yolo_predict(self, image, *args):
        self.calls += 1
        if self.calls == 1:
            self.entered.set()
            if self.gate:
                self.release.wait(5)
            if self.fail_first:
                raise RuntimeError("Synthetic test inference failure")
        return [Detection("car", [10, 10, 40, 40], 0.9, "yolo")]


class WorkerRegressionTests(StudioTestCase):
    def setup_job(self, **kwargs):
        self.add_image("cam_a/a.png", "red")
        self.add_image("cam_a/b.png", "blue")
        self.hub = FakeHub(**kwargs)
        self.runner.hub = self.hub
        return {"yolo_model": str(self.root / "fake.pt"), "device": "cpu"}

    def current(self):
        with store.connect() as db:
            return dict(
                db.execute("SELECT * FROM jobs ORDER BY id DESC LIMIT 1").fetchone()
            )

    def wait_state(self, state):
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            if self.current()["state"] == state:
                return
            time.sleep(0.01)
        self.fail(f"Expected {state}, got {self.current()}")

    def test_safe_stop_then_resume_preserves_denominator_and_results(self):
        cfg = self.setup_job(gate=True)
        jid = self.runner.start(cfg)
        self.assertTrue(self.hub.entered.wait(2))
        self.runner.stop()
        self.assertEqual(self.current()["state"], "stopping")
        self.assertEqual(self.client.post("/api/datasets/clear").status_code, 409)
        self.hub.release.set()
        self.runner.thread.join(4)
        job = self.current()
        self.assertEqual(job["state"], "stopped")
        self.assertEqual((job["total"], job["processed"]), (2, 1))
        self.runner.resume()
        self.runner.thread.join(4)
        job = self.current()
        self.assertEqual(job["id"], jid)
        self.assertEqual(job["state"], "completed")
        self.assertEqual((job["total"], job["processed"], job["failed"]), (2, 2, 0))
        self.assertEqual(self.client.get("/api/stats").json()["job"]["percent"], 100)
        with store.connect() as db:
            self.assertEqual(
                db.execute("SELECT count(*) FROM annotations").fetchone()[0], 2
            )

    def test_pause_at_image_boundary_and_resume(self):
        cfg = self.setup_job(gate=True)
        self.runner.start(cfg)
        self.assertTrue(self.hub.entered.wait(2))
        self.runner.pause()
        self.hub.release.set()
        self.wait_state("paused")
        self.assertEqual(self.hub.calls, 1)
        self.runner.resume()
        self.runner.thread.join(4)
        self.assertEqual(self.current()["state"], "completed")
        self.assertEqual(self.hub.calls, 2)

    def test_retry_failure_does_not_double_count_successes(self):
        cfg = self.setup_job(fail_first=True)
        self.runner.start(cfg)
        self.runner.thread.join(4)
        self.assertEqual(self.current()["state"], "completed_with_errors")
        self.runner.resume()
        self.runner.thread.join(4)
        job = self.current()
        self.assertEqual((job["total"], job["processed"], job["failed"]), (2, 2, 0))
        self.assertEqual(self.hub.calls, 3)

    def test_cancel_is_distinct_and_completed_images_survive(self):
        cfg = self.setup_job(gate=True)
        self.runner.start(cfg)
        self.assertTrue(self.hub.entered.wait(2))
        self.runner.cancel()
        self.hub.release.set()
        self.runner.thread.join(4)
        self.assertEqual(self.current()["state"], "cancelled")
        with self.assertRaises(RuntimeError):
            self.runner.resume()
        with store.connect() as db:
            self.assertEqual(
                db.execute("SELECT count(*) FROM annotations").fetchone()[0], 1
            )

    def test_recovered_job_items_resume_after_restart(self):
        cfg = self.setup_job()
        with store.connect() as db:
            jid = db.execute(
                "INSERT INTO jobs(state,config,total) VALUES('running',?,2)",
                (json.dumps(cfg),),
            ).lastrowid
            db.execute(
                "INSERT INTO job_items(job_id,image_id,state) VALUES(?,1,'processing')",
                (jid,),
            )
            db.execute(
                "INSERT INTO job_items(job_id,image_id,state) VALUES(?,2,'pending')",
                (jid,),
            )
            db.execute("UPDATE images SET status='processing' WHERE id=1")
        store.init_db()
        self.assertEqual(self.current()["state"], "paused")
        self.runner.resume()
        self.runner.thread.join(4)
        self.assertEqual(self.current()["processed"], 2)

    def test_original_labels_are_not_duplicated_and_outputs_are_proposals(self):
        cfg = self.setup_job()
        self.add_box(1, source="original", accepted=1)
        cfg["output_dir"] = str(self.root / "output")
        self.runner.start(cfg)
        self.runner.thread.join(4)
        self.assertEqual(self.hub.calls, 1)
        with store.connect() as db:
            self.assertEqual(
                db.execute(
                    "SELECT count(*) FROM annotations WHERE image_id=1"
                ).fetchone()[0],
                1,
            )
        paths = list((self.root / "output").rglob("*"))
        self.assertTrue(any(p.suffix == ".json" for p in paths))
        self.assertFalse(any(p.name == "data.yaml" for p in paths))
        self.assertFalse(any(p.parent.name == "labels" for p in paths))

    def test_nonfinite_or_degenerate_model_boxes_never_reach_storage(self):
        bad = [
            Detection("car", [0, 0, float("nan"), 20], 0.9, "yolo"),
            Detection("car", [50, 1, 10, 20], 0.9, "yolo"),
        ]
        self.assertEqual(match_and_score(bad, [], 100, 80), [])

    def test_automatic_traffic_pass_and_resume_after_detection(self):
        cfg = self.setup_job()
        cfg["analyze_traffic_after"] = True
        self.runner.start(cfg)
        self.runner.thread.join(4)
        self.assertEqual(self.current()["state"], "completed")
        with store.connect() as db:
            self.assertEqual(
                db.execute("SELECT count(*) FROM traffic_measurements").fetchone()[0], 2
            )
            db.execute("UPDATE jobs SET state='stopped'")
            db.execute("DELETE FROM traffic_measurements")
        self.runner.resume()
        self.runner.thread.join(4)
        self.assertEqual(self.hub.calls, 2)  # No repeat inference for completed images.
        with store.connect() as db:
            self.assertEqual(
                db.execute("SELECT count(*) FROM traffic_measurements").fetchone()[0], 2
            )
        self.assertFalse(self.runner.maintenance)


class MigrationTests(StudioTestCase):
    def test_additive_upgrade_backs_up_and_retains_existing_rows(self):
        iid = self.add_image()
        self.add_box(iid)
        with store.connect() as db:
            db.execute("ALTER TABLE images DROP COLUMN review_version")
            db.execute("DROP INDEX idx_images_review")
            db.execute("ALTER TABLE images DROP COLUMN review_state")
            db.execute("PRAGMA user_version=0")
        store.init_db()
        self.assertEqual(self.client.get("/api/stats").json()["images"], 1)
        self.assertEqual(
            self.client.get(f"/api/images/{iid}").json()["image"]["review_version"], 0
        )
        self.assertEqual(
            len(list((self.data / "backups").glob("pre-v04-*.sqlite3"))), 1
        )
