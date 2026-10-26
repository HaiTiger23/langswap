import unittest
from local_dub.pacing import plan_pacing

class PacingTests(unittest.TestCase):
 def test_different_length_sentences_share_a_cadence(self):
  rows=[dict(start=0,end=3,vi=' '.join(['từ']*6)),dict(start=4,end=7,vi=' '.join(['từ']*12)),dict(start=8,end=11,vi=' '.join(['từ']*9))]
  p=plan_pacing(rows,12)
  self.assertFalse(p['rewrite_requests'])
  self.assertLess(max(r['expected_sps'] for r in p['plans'])-min(r['expected_sps'] for r in p['plans']),.01)
  self.assertTrue(all(r['fit_end']<=s['end']+.25 for s,r in zip(rows,p['plans'])))
 def test_isolated_dense_sentence_does_not_accelerate_everything(self):
  rows=[dict(start=i*4,end=i*4+3,vi=' '.join(['từ']*(30 if i==4 else 12))) for i in range(5)]
  p=plan_pacing(rows,20)
  self.assertEqual(set(p['rewrite_requests']),{'4'})
  self.assertLessEqual(p['target_sps'],7)
  self.assertLess(p['rewrite_requests']['4']['budget'],30)
 def test_pause_lending_never_crosses_next_source_start(self):
  rows=[dict(start=1,end=2,vi='Xin chào'),dict(start=2.1,end=4,vi='Bạn khỏe không')]
  p=plan_pacing(rows,5)
  self.assertLessEqual(p['plans'][0]['fit_end'],2.02+.0001)
  self.assertEqual(rows[0]['start'],1)
 def test_bad_timestamps_fail(self):
  with self.assertRaises(ValueError):plan_pacing([dict(start=3,end=2,vi='Chào')],2)
