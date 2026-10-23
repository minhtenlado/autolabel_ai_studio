import io
import json
import math
import zipfile
from pathlib import Path
from PIL import Image
from backend.database import store
from backend.dataset import operations
from support import StudioTestCase


class ReviewAPITests(StudioTestCase):
    def test_review_preserves_evidence_and_rejects_stale_tab(self):
        iid = self.add_image()
        metadata = {
            "yolo": {"class_name": "car", "box": [10, 10, 30, 30]},
            "sam": {"mask_derived_box": [9, 9, 31, 31]},
        }
        aid = self.add_box(iid, metadata=json.dumps(metadata))
        payload = [
            {
                "id": aid,
                "class_name": "truck",
                "box": [11, 12, 31, 33],
                "accepted": True,
            }
        ]
        result = self.review(iid, payload, complete=True)
        self.assertEqual(result.status_code, 200, result.text)
        detail = self.client.get(f"/api/images/{iid}").json()
        self.assertEqual(detail["annotations"][0]["metadata"]["sam"], metadata["sam"])
        self.assertEqual(detail["image"]["review_state"], "reviewed")
        self.assertEqual(detail["annotations"][0]["quality"], "human_reviewed")
        self.assertEqual(self.review(iid, payload, complete=True).status_code, 409)
        self.assertEqual(self.client.get("/api/stats").json()["reviewed_images"], 1)

    def test_validation_is_atomic_duplicate_id_and_bad_box(self):
        iid = self.add_image()
        aid = self.add_box(iid)
        good = {"id": aid, "class_name": "truck", "box": [1, 1, 40, 40]}
        for payload in (
            [good, good],
            [good, {"class_name": "car", "box": [1, 1, 200, 30]}],
        ):
            result = self.review(iid, payload, complete=True)
            self.assertEqual(result.status_code, 422, result.text)
            detail = self.client.get(f"/api/images/{iid}").json()
            self.assertEqual(detail["annotations"][0]["class_name"], "car")
            self.assertEqual(detail["image"]["review_version"], 0)

    def test_negative_requires_explicit_confirmation_and_is_exported(self):
        iid = self.add_image()
        self.assertEqual(self.review(iid, complete=True).status_code, 422)
        self.assertEqual(
            self.review(iid, complete=True, negative=True).status_code, 200
        )
        result = self.client.post("/api/export", json={"name": "negative"}).json()
        self.assertEqual(result["negative_images"], 1)
        archive = self.client.get(result["download_url"])
        self.assertEqual(archive.status_code, 200)
        with zipfile.ZipFile(io.BytesIO(archive.content)) as z:
            labels = [n for n in z.namelist() if "/labels/" in n and n.endswith(".txt")]
            self.assertEqual(len(labels), 1)
            self.assertEqual(z.read(labels[0]), b"")

    def test_pseudo_export_keeps_all_boxes_even_when_only_some_are_accepted(self):
        iid = self.add_image(status="processed")
        self.add_box(iid, accepted=1)
        self.add_box(iid, accepted=0)
        result = self.client.post("/api/export", json={"include_pseudo": True})
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json()["images"], 1)
        self.assertEqual(result.json()["pseudo_labels"], 1)

    def test_partial_stopped_job_can_export_only_completed_images(self):
        first = self.add_image("cam_a/first.png", status="processed")
        self.add_box(first, accepted=1)
        self.add_box(first, accepted=0)
        second = self.add_image("cam_a/second.png", color="blue", status="processed")
        self.add_box(second, accepted=0)
        pending = self.add_image("cam_a/pending.png", color="green", status="pending")
        self.add_box(pending, accepted=1)
        self.add_image("cam_a/empty.png", color="yellow", status="processed")
        invalid = self.add_image("cam_a/invalid.png", color="purple", status="processed")
        invalid_box = self.add_box(invalid, accepted=0)
        with store.connect() as db:
            db.execute(
                "UPDATE annotations SET class_id=-1 WHERE id=?", (invalid_box,)
            )

        result = self.client.post("/api/export", json={"include_pseudo": True})
        self.assertEqual(result.status_code, 200, result.text)
        payload = result.json()
        self.assertEqual(payload["images"], 2)
        self.assertEqual(payload["pseudo_labels"], 2)
        self.assertEqual(payload["negative_images"], 0)
        self.assertEqual(payload["pseudo_empty_excluded"], 1)
        self.assertEqual(payload["pseudo_invalid_excluded"], 1)

        archive = self.client.get(payload["download_url"])
        self.assertEqual(archive.status_code, 200)
        with zipfile.ZipFile(io.BytesIO(archive.content)) as z:
            manifest = json.loads(
                z.read(next(n for n in z.namelist() if n.endswith("manifest.json")))
            )
            self.assertEqual({row["image_id"] for row in manifest}, {first, second})
            self.assertTrue(
                all(
                    row["acceptance_policy"] == "pseudo_label_unreviewed"
                    for row in manifest
                )
            )
            labels = [n for n in z.namelist() if "/labels/" in n and n.endswith(".txt")]
            self.assertEqual(sum(len(z.read(name).splitlines()) for name in labels), 3)

    def test_export_default_excludes_ai_but_opt_in_allows_full_proposal(self):
        iid = self.add_image(status="processed")
        self.add_box(iid, accepted=1)
        self.assertEqual(self.client.post("/api/export", json={}).status_code, 400)
        result = self.client.post("/api/export", json={"include_pseudo": True}).json()
        self.assertEqual(result["images"], 1)
        self.assertEqual(result["pseudo_labels"], 1)

    def test_review_processing_image_and_maintenance_are_blocked(self):
        iid = self.add_image(status="processing")
        self.assertEqual(
            self.review(iid, complete=True, negative=True).status_code, 409
        )
        self.runner.maintenance = True
        self.assertEqual(
            self.review(iid, complete=True, negative=True).status_code, 409
        )
        self.runner.maintenance = False

    def test_filters_pagination_and_validation(self):
        a = self.add_image()
        b = self.add_image("cam_b/b.png", "blue")
        self.add_box(b, quality="high_risk")
        self.assertEqual(
            self.client.get("/api/images?review=high_risk").json()["items"][0]["id"], b
        )
        self.assertEqual(
            self.client.get("/api/images?limit=1&offset=1").json()["items"][0]["id"], b
        )
        self.assertEqual(self.client.get("/api/images?offset=-1").status_code, 422)
        self.assertEqual(self.client.get("/api/images?limit=2000").status_code, 422)

    def test_thumbnail_is_small_and_missing_source_is_clear_error(self):
        iid = self.add_image()
        response = self.client.get(f"/api/images/{iid}/thumbnail")
        self.assertEqual(response.status_code, 200)
        with Image.open(io.BytesIO(response.content)) as thumb:
            self.assertLessEqual(thumb.width, 320)
        with store.connect() as db:
            path = db.execute("SELECT path FROM images WHERE id=?", (iid,)).fetchone()[
                0
            ]
        Path(path).unlink()
        self.assertEqual(self.client.get(f"/api/images/{iid}/file").status_code, 404)

    def test_cross_origin_write_is_rejected(self):
        response = self.client.post(
            "/api/datasets/clear", headers={"origin": "https://other-site.test"}
        )
        self.assertEqual(response.status_code, 403)


class ImportExportTests(StudioTestCase):
    def test_replacement_cannot_reuse_stale_browser_image_id(self):
        old = self.add_image()
        self.add_box(old)
        root = self.root / "replacement"
        root.mkdir()
        Image.new("RGB", (100, 80), "green").save(root / "new.png")
        result = self.client.post(
            "/api/datasets/import", json={"folder": str(root), "clear_first": True}
        )
        self.assertEqual(result.status_code, 200, result.text)
        new = self.client.get("/api/images").json()["items"][0]["id"]
        self.assertGreater(new, old)
        self.assertEqual(
            self.review(old, complete=True, negative=True).status_code, 404
        )
        self.assertEqual(
            self.client.get(f"/api/images/{new}").json()["image"]["review_state"],
            "unreviewed",
        )

    def test_same_content_across_camera_days_stays_in_one_split(self):
        from backend.dataset.exports import split_groups

        rows = [
            {"id": 1, "camera_id": "a", "timestamp": "2026-10-22", "sha256": "same"},
            {"id": 2, "camera_id": "b", "timestamp": "2026-10-23", "sha256": "same"},
            {
                "id": 3,
                "camera_id": "b",
                "timestamp": "2026-10-23",
                "sha256": "different",
            },
        ]
        splits, groups, warnings = split_groups(rows)
        self.assertEqual(len(set(splits.values())), 1)
        self.assertEqual(len(set(groups.values())), 1)
        self.assertTrue(warnings)

    def test_yolo_yaml_names_remap_original_class_ids(self):
        root = self.root / "dataset"
        root.mkdir()
        Image.new("RGB", (100, 80), "green").save(root / "image.png")
        (root / "image.txt").write_text("0 0.5 0.5 0.2 0.2\n")
        (root / "data.yaml").write_text("names: [truck, car]\n")
        result = operations.import_folder(root)
        box = self.client.get("/api/images/1").json()["annotations"][0]
        self.assertEqual(box["class_name"], "truck")
        self.assertEqual(box["class_id"], operations.CLASSES.index("truck"))
        self.assertEqual(result["class_mapping"], str(root / "data.yaml"))

    def test_invalid_yaml_does_not_clear_existing_dataset(self):
        self.add_image()
        root = self.root / "dataset"
        root.mkdir()
        Image.new("RGB", (100, 80), "green").save(root / "image.png")
        (root / "data.yaml").write_text("names: [\n")
        result = self.client.post(
            "/api/datasets/import", json={"folder": str(root), "clear_first": True}
        )
        self.assertEqual(result.status_code, 400)
        self.assertEqual(self.client.get("/api/stats").json()["images"], 1)

    def test_keep_duplicates_preserves_distinct_frames_but_not_same_path(self):
        root = self.root / "dataset"
        root.mkdir()
        for name in ("20261022_120000.png", "20261022_120001.png"):
            Image.new("RGB", (100, 80), "green").save(root / name)
        result = operations.import_folder(root, keep_duplicates=True)
        self.assertEqual(result["added"], 2)
        self.assertEqual(result["retained_duplicates"], 1)
        self.assertEqual(
            operations.import_folder(root, keep_duplicates=True)["added"], 0
        )

    def test_invalid_empty_or_corrupt_replacement_keeps_old_dataset(self):
        iid = self.add_image()
        self.add_box(iid)
        empty = self.root / "empty"
        empty.mkdir()
        corrupt = self.root / "corrupt"
        corrupt.mkdir()
        (corrupt / "bad.jpg").write_bytes(b"no jpeg")
        for path in [self.root / "missing", empty, corrupt]:
            response = self.client.post(
                "/api/datasets/import", json={"folder": str(path), "clear_first": True}
            )
            self.assertEqual(response.status_code, 400, response.text)
            self.assertEqual(self.client.get("/api/stats").json()["images"], 1)
            self.assertEqual(
                len(self.client.get(f"/api/images/{iid}").json()["annotations"]), 1
            )

    def test_nested_yolo_labels_and_duplicate_detection(self):
        root = self.root / "dataset"
        folder = root / "images/train/cam_a"
        folder.mkdir(parents=True)
        label = root / "labels/train/cam_a"
        label.mkdir(parents=True)
        Image.new("RGB", (100, 80), "green").save(folder / "20261022_120000.png")
        (label / "20261022_120000.txt").write_text(
            "1 0.5 0.5 0.2 0.2\n1 0.5 0.5 0 0.2\n1 0.5 0.5 0.2 0.2 0.5\n"
        )
        result = operations.import_folder(root)
        self.assertEqual(result["added"], 1)
        self.assertEqual(result["label_errors"], 2)
        detail = self.client.get("/api/images/1").json()
        self.assertEqual(detail["image"]["camera_id"], "cam_a")
        self.assertEqual(len(detail["annotations"]), 1)
        self.assertIsNotNone(detail["image"]["error"])
        self.assertEqual(operations.import_folder(root)["duplicates"], 1)
        # Partial broken imported labels must not bypass human review.
        self.assertEqual(self.client.post("/api/export", json={}).status_code, 400)

    def test_empty_imported_label_is_not_verified_negative(self):
        root = self.root / "input"
        root.mkdir()
        Image.new("RGB", (30, 30), "gray").save(root / "empty.png")
        (root / "empty.txt").write_text("")
        operations.import_folder(root)
        self.assertEqual(
            self.client.get("/api/images/1").json()["image"]["review_state"],
            "unreviewed",
        )
        self.assertEqual(self.client.post("/api/export", json={}).status_code, 400)

    def test_full_image_decode_catches_truncation(self):
        root = self.root / "input"
        root.mkdir()
        target = root / "bad.png"
        Image.new("RGB", (100, 80), "purple").save(target)
        target.write_bytes(target.read_bytes()[:60])
        result = operations.import_folder(root)
        self.assertEqual(result["broken"], 1)
        self.assertEqual(result["added"], 0)

    def test_snapshot_names_never_overwrite_and_groups_do_not_leak(self):
        for i in range(4):
            iid = self.add_image(
                f"cam_a/frame_{i}.png", ("red", "green", "blue", "white")[i]
            )
            self.review(
                iid, [{"class_name": "car", "box": [1, 1, 10, 10]}], complete=True
            )
            with store.connect() as db:
                db.execute(
                    "UPDATE images SET timestamp=? WHERE id=?",
                    ("2026-10-" + ("22" if i < 2 else "23") + " 12:00:00", iid),
                )
        parent = self.root / "custom"
        parent.mkdir()
        (parent / "keep.txt").write_text("keep")
        first = operations.export_dataset("same", str(parent))
        second = operations.export_dataset("same", str(parent))
        self.assertNotEqual(first["path"], second["path"])
        self.assertEqual((parent / "keep.txt").read_text(), "keep")
        manifest = json.loads((Path(first["path"]) / "manifest.json").read_text())
        groups = {}
        for row in manifest:
            groups.setdefault(row["group"], set()).add(row["split"])
        self.assertTrue(all(len(values) == 1 for values in groups.values()))
        self.assertEqual(first["train"], 2)
        self.assertEqual(first["val"], 2)

    def test_async_import_progress_and_mutation_gate(self):
        import threading
        from unittest.mock import patch
        from support import api_module

        started, release = threading.Event(), threading.Event()

        def slow(folder, clear, progress, keep_duplicates=False):
            progress(1, 2, "testing")
            started.set()
            release.wait(5)
            return {"added": 2}

        with patch.object(api_module, "import_folder", slow):
            response = self.client.post(
                "/api/datasets/import",
                json={"folder": str(self.root), "background": True},
            )
            self.assertEqual(response.status_code, 200)
            tid = response.json()["task_id"]
            self.assertTrue(started.wait(2))
            task = self.client.get(f"/api/tasks/{tid}").json()
            self.assertEqual(task["completed"], 1)
            self.assertEqual(self.client.post("/api/datasets/clear").status_code, 409)
            release.set()
            api_module.tasks.thread.join(3)
            self.assertEqual(
                self.client.get(f"/api/tasks/{tid}").json()["state"], "completed"
            )
