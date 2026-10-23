import json
from pathlib import Path
from support import StudioTestCase
from backend.database import store
from backend.traffic import analysis


class TrafficRegressionTests(StudioTestCase):
    def prepare(self):
        iid = self.add_image(status="processed")
        self.add_box(iid, accepted=1)
        analysis.save_roi(
            "cam_a",
            {
                "rois": [{"type": "road", "polygon": [[0, 0], [1, 0], [1, 1], [0, 1]]}],
                "calibration": {"free_max": 0, "busy_max": 2, "jam_min": 5},
                "calibration_confirmed": True,
            },
        )
        analysis.analyze_all()
        return iid

    def test_manual_label_survives_reanalysis_csv_and_classification(self):
        iid = self.prepare()
        analysis.set_label(iid, "Un_tac_nang")
        analysis.analyze_all()
        row = analysis.list_labels()[0]
        features = json.loads(row["features_json"])
        self.assertEqual(row["predicted_class"], "Un_tac_nang")
        self.assertEqual(features["predicted_traffic_class"], "Un_tac_nang")
        self.assertEqual(features["class_id"], 3)
        self.assertEqual(features["label_source"], "human_verified")
        record = analysis.temporal_records()[0]
        self.assertEqual(record["traffic_class_id"], 3)
        self.assertEqual(record["traffic_class_name"], "Un_tac_nang")
        result = analysis.export_classification()
        self.assertEqual(result["images"], 1)
        manifest = json.loads((Path(result["path"]) / "manifest.json").read_text())
        self.assertFalse(manifest[0]["pseudo_label"])

    def test_rejected_label_stays_rejected_after_analyze(self):
        iid = self.prepare()
        analysis.set_label(iid, "Dong_xe", False)
        analysis.analyze_all()
        self.assertEqual(analysis.list_labels()[0]["review_status"], "rejected")
        with self.assertRaises(ValueError):
            analysis.export_classification(include_pseudo=True)

    def test_rejected_boxes_and_exclusion_are_not_counted(self):
        iid = self.prepare()
        self.add_box(iid, accepted=0, reviewed=1)
        self.add_box(iid, accepted=1)
        analysis.analyze_all()
        f = json.loads(analysis.list_labels()[0]["features_json"])
        self.assertEqual(f["total_vehicle_count"], 2)
        cfg = analysis.get_roi("cam_a")
        cfg["rois"].append(
            {
                "type": "exclusion",
                "polygon": [[0.05, 0.05], [0.4, 0.05], [0.4, 0.5], [0.05, 0.5]],
            }
        )
        analysis.save_roi("cam_a", cfg)
        analysis.analyze_all()
        f = json.loads(analysis.list_labels()[0]["features_json"])
        self.assertEqual(f["total_vehicle_count"], 0)

    def test_csv_has_more_than_2000_rows_and_pagination_is_independent(self):
        iid = self.prepare()
        template = analysis.list_labels()[0]
        with store.connect() as db:
            for n in range(2005):
                image_id = db.execute(
                    "INSERT INTO images(path,rel_path,sha256,width,height,camera_id,timestamp,status) VALUES(?,?,?,?,?,?,?,?)",
                    (
                        f"/tmp/test-{n}.png",
                        f"frame-{n}",
                        str(n).zfill(64),
                        100,
                        80,
                        "cam_a",
                        "2026-10-22 12:00:00",
                        "processed",
                    ),
                ).lastrowid
                db.execute(
                    "INSERT INTO traffic_measurements(image_id,camera_id,timestamp,features_json,predicted_class,quality,review_status) VALUES(?,?,?,?,?,?,?)",
                    (
                        image_id,
                        "cam_a",
                        "2026-10-22 12:00:00",
                        template["features_json"],
                        template["predicted_class"],
                        template["quality"],
                        template["review_status"],
                    ),
                )
        self.assertEqual(len(analysis.temporal_records()), 2006)
        response = self.client.get("/api/traffic/labels?offset=2000&limit=30").json()
        self.assertEqual(response["total"], 2006)
        self.assertEqual(len(response["items"]), 6)
        result = analysis.export_traffic()
        self.assertEqual(result["records"], 2006)

    def test_roi_changes_make_temporal_features_stale_until_reanalysis(self):
        self.prepare()
        analysis.save_roi("cam_a", analysis.get_roi("cam_a"))
        with self.assertRaisesRegex(ValueError, "phân tích lại"):
            analysis.temporal_records()
        analysis.analyze_all()
        self.assertEqual(len(analysis.temporal_records()), 1)

    def test_roi_rejects_zero_area_crossings_and_bad_thresholds(self):
        invalid = [
            {"rois": [{"type": "road", "polygon": [[0, 0], [0.5, 0.5], [1, 1]]}]},
            {"rois": [{"type": "road", "polygon": [[0, 0], [1, 1], [0, 1], [1, 0]]}]},
            {"calibration": {"free_max": 4, "busy_max": 3, "jam_min": 6}},
        ]
        for cfg in invalid:
            with self.assertRaises(ValueError):
                analysis.save_roi("cam_a", cfg)
