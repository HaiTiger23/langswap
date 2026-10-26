import unittest
from local_dub.subtitle_ocr import merge_fragments

class SubtitleGroupingTests(unittest.TestCase):
 def test_contiguous_fragments_preserve_all_words_and_timeline(self):
  rows=[dict(start=4.75,end=6.75,zh='不你那眼睛是跟脚长一块了'),dict(start=6.75,end=7.25,zh='是怎么的'),dict(start=7.25,end=8,zh='这这么短'),dict(start=8.25,end=9.75,zh='你让我怎么插进去呗')]
  out=merge_fragments(rows)
  self.assertEqual(len(out),1)
  self.assertEqual((out[0]['start'],out[0]['end']),(4.75,9.75))
  self.assertEqual(out[0]['zh'],'，'.join(r['zh'] for r in rows))
  self.assertEqual(rows[0]['end'],6.75)
 def test_respects_long_pauses_and_maximum_window(self):
  rows=[dict(start=0,end=2,zh='甲'),dict(start=3,end=5,zh='乙'),dict(start=5,end=10,zh='丙')]
  self.assertEqual(len(merge_fragments(rows)),3)
