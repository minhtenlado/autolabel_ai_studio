import json, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
from backend.database import store
from backend.traffic import analysis

class TrafficAnalysisTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        root=Path(self.tmp.name)
        self.db_path=root/'test.sqlite3'
        self.data_path=root/'workspace'
        self.p1=patch.object(store,'DB_PATH',self.db_path); self.p2=patch.object(store,'DATA_ROOT',self.data_path)
        self.p1.start(); self.p2.start(); store.init_db()
    def tearDown(self):
        self.p2.stop(); self.p1.stop(); self.tmp.cleanup()
    def test_polygon_contains_road_point(self):
        poly=[[.1,.1],[.9,.1],[.9,.9],[.1,.9]]
        self.assertTrue(analysis.inside((.5,.5),poly))
        self.assertFalse(analysis.inside((.02,.5),poly))
    def test_camera_thresholds_make_provisional_state_and_proxy(self):
        with store.connect() as db:
            db.execute("INSERT INTO images(path,rel_path,sha256,width,height,camera_id,timestamp,status) VALUES(?,?,?,?,?,?,?,'processed')",('/tmp/no-copy.jpg','cam-a/frame_20261021_120000.jpg','a'*64,100,100,'cam-a','2026-10-21 12:00:00'))
            iid=db.execute('SELECT last_insert_rowid()').fetchone()[0]
            for n in range(2):db.execute("INSERT INTO annotations(image_id,source,class_name,class_id,x1,y1,x2,y2,quality,accepted,metadata) VALUES(?,?,?,?,?,?,?,?,?,?,?)",(iid,'manual','car',1,30+n*20,40,40+n*20,60,'human_reviewed',1,'{}'))
        analysis.save_roi('cam-a',{'rois':[{'type':'road','status':'confirmed','polygon':[[0,0],[1,0],[1,1],[0,1]]}],'calibration':{'free_max':0,'busy_max':1,'queue_min':2,'jam_min':3},'calibration_confirmed':True})
        result=analysis.analyze_all(); self.assertEqual(result['labeled'],1)
        f=result['items'][0]; self.assertEqual(f['predicted_traffic_class'],'Un_u_nhe')
        self.assertEqual(f['road_pixel_occupancy'],None)
        self.assertGreater(f['box_occupancy_proxy'],0)
        self.assertEqual(f['label_source'],'camera_rule_pseudo_label')
    def test_missing_roi_and_calibration_never_invents_label(self):
        with store.connect() as db:db.execute("INSERT INTO images(path,rel_path,sha256,width,height,camera_id) VALUES(?,?,?,?,?,?)",('/tmp/a.jpg','a.jpg','b'*64,20,20,'cam-b'))
        result=analysis.analyze_all();f=next(i for i in result['items'] if i['camera_id']=='cam-b')
        self.assertIsNone(f['predicted_traffic_class']);self.assertEqual(f['review_status'],'needs_review')
        self.assertIn('missing_confirmed_road_roi',f['reasons'])

if __name__=='__main__':unittest.main()
