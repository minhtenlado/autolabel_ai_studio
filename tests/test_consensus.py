import unittest
from backend.consensus.engine import Detection, iou, match_and_score

class ConsensusTests(unittest.TestCase):
    def test_iou(self):
        self.assertAlmostEqual(iou([0,0,10,10],[5,5,15,15]),25/175)
    def test_one_to_one_and_conflict(self):
        y=[Detection('truck',[0,0,20,20],.91,'yolo'),Detection('car',[20,0,40,20],.83,'yolo')]
        d=[Detection('container',[1,0,21,20],.87,'grounding_dino')]
        result=match_and_score(y,d,50,40,match_iou=.4)
        self.assertEqual(len(result),2)
        self.assertEqual(result[0]['quality'],'high_risk')
        self.assertEqual(result[0]['metadata']['agreement'],'class_conflict')
        self.assertEqual(result[1]['source'],'yolo_only')
        self.assertFalse(any(x['accepted'] for x in result))
    def test_agreement_is_not_auto_accepted(self):
        a=Detection('car',[1,2,20,30],.9,'yolo'); b=Detection('car',[2,2,21,30],.8,'grounding_dino')
        result=match_and_score([a],[b],40,40)
        self.assertEqual(result[0]['quality'],'high_agreement')
        self.assertFalse(result[0]['accepted'])
    def test_ambiguous_dino_is_high_risk(self):
        result=match_and_score([], [Detection('ambiguous',[0,0,12,12],.5,'grounding_dino',True)],40,40)
        self.assertEqual(result[0]['quality'],'high_risk')
        self.assertFalse(result[0]['accepted'])

if __name__=='__main__': unittest.main()
