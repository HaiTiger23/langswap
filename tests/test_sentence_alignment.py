import unittest
from local_dub.sentence_alignment import anchors_from_words,validate_partition

class SentenceAlignmentTests(unittest.TestCase):
 def test_measured_word_starts_preserve_real_pauses(self):
  words=[dict(word='第一句。',start=1,end=2.4),dict(word='第二句。',start=4,end=5.6)]
  out=anchors_from_words(words,0,0,6)
  self.assertEqual([(s['start'],s['end']) for s in out],[(1,2.4),(4,5.6)])
  self.assertTrue(all(s['block_id']==0 for s in out))
 def test_partition_cannot_drop_rewrite_or_duplicate_translation(self):
  blocks=[dict(vi='Dùng túi ni lông, lau bếp sạch bóng.')]
  anchors=[dict(block_id=0),dict(block_id=0)]
  validate_partition({0:'Dùng túi ni lông.',1:'Lau bếp sạch bóng!'},anchors,blocks)
  for bad in [{0:'Dùng túi.',1:'Lau bếp sạch bóng.'},{0:'Lau bếp sạch bóng.',1:'Dùng túi ni lông.'},{0:'Dùng túi ni lông.',1:'Lau bếp sạch bóng sạch bóng.'}]:
   with self.subTest(bad=bad),self.assertRaises(ValueError):validate_partition(bad,anchors,blocks)
 def test_partition_cannot_move_words_between_blocks(self):
  with self.assertRaises(ValueError):validate_partition({0:'Xin chào bạn',1:'nhé'},[dict(block_id=0),dict(block_id=1)],[dict(vi='Xin chào'),dict(vi='bạn nhé')])
 def test_invalid_time_is_not_fabricated(self):
  with self.assertRaises(ValueError):anchors_from_words([dict(word='你好',start=2,end=2)],0,0,5)
