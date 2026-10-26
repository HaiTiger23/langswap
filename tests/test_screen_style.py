import unittest
import numpy as np
from PIL import Image,ImageDraw,ImageFont
from local_dub.screen_style import consolidate_labels,anchor_at,make_label_tile,cleanup_text

class ScreenStyleTests(unittest.TestCase):
 def region(self,id,vi,start,end,delta=0):
  return dict(id=id,vi=vi,text='油腻灶台',kind='label',mask_only=False,start=start,end=end,samples=[dict(time=start+i*.03,box=[.3+(-1)**i*delta,.3,.3,.04]) for i in range(10)])
 def test_duplicate_ocr_variants_render_as_one_occurrence(self):
  groups=consolidate_labels([self.region(1,'Mặt bếp dính dầu mỡ',1,2),self.region(2,'Mặt bếp dính dầu mỡ',1.2,2.3)])
  self.assertEqual(len(groups),1)
  self.assertEqual(set(groups[0]['members']),{1,2})
 def test_short_translation_fragment_does_not_flash_before_full_label(self):
  a=self.region(1,'Đơn giản',1,1.4);b=self.region(2,'Đơn giản hiệu quả',1.2,2.3);b['samples']*=2
  groups=consolidate_labels([a,b]);self.assertEqual(len(groups),1);self.assertEqual(groups[0]['vi'],'Đơn giản hiệu quả')
 def test_ocr_jitter_does_not_move_or_resize_label(self):
  label=consolidate_labels([self.region(1,'Nước rửa chén',1,2,delta=.012)])[0]
  self.assertFalse(label['moving'])
  self.assertEqual(anchor_at(label,1.1),anchor_at(label,1.8))
  tile,style=make_label_tile(label,720,1280,dict(fill=(255,255,255),stroke=(0,0,0),stroke_width=2))
  alpha=np.asarray(tile)[:,:,3]
  self.assertLess(np.count_nonzero(alpha)/alpha.size,.65)
  self.assertEqual(alpha[0,0],0)
  self.assertEqual(len(style['lines']),1)
 def test_cleanup_is_glyph_local_and_does_not_paint_a_rectangle(self):
  image=Image.new('RGB',(250,65),(110,130,145));draw=ImageDraw.Draw(image)
  draw.text((30,5),'TEST',font=ImageFont.truetype('/System/Library/Fonts/Supplemental/Arial Bold.ttf',38),fill='white',stroke_width=2,stroke_fill='black')
  original=np.asarray(image);clean=cleanup_text(original,38)
  self.assertTrue(np.array_equal(original[:,:20],clean[:,:20]))
  self.assertLess(np.mean(np.abs(clean.astype(float)-np.array([110,130,145]))),np.mean(np.abs(original.astype(float)-np.array([110,130,145]))))

 def test_dark_ink_on_yellow_background_is_removed_too(self):
  image=Image.new('RGB',(260,65),(255,225,20));draw=ImageDraw.Draw(image)
  draw.text((30,5),'TEST',font=ImageFont.truetype('/System/Library/Fonts/Supplemental/Arial Bold.ttf',38),fill='black')
  original=np.asarray(image);clean=cleanup_text(original,38)
  target=np.array([255,225,20])
  self.assertLess(np.mean(np.abs(clean.astype(float)-target)),np.mean(np.abs(original.astype(float)-target))*.35)
 def test_captions_in_same_slot_never_stack_during_transition(self):
  a=self.region(1,'Túi ni lông',1,2);b=self.region(2,'Nước rửa chén',1.9,3);b['text']='洗洁精'
  groups=consolidate_labels([a,b])
  self.assertEqual(len(groups),2)
  self.assertLessEqual(groups[0]['end'],groups[1]['start'])
 def test_connected_outline_is_not_dropped_as_background(self):
  image=Image.new('RGB',(260,65),'white');draw=ImageDraw.Draw(image)
  draw.text((25,5),'TEST',font=ImageFont.truetype('/System/Library/Fonts/Supplemental/Arial Bold.ttf',38),fill='white',stroke_width=3,stroke_fill='black')
  draw.line((0,46,259,46),fill='black',width=3)
  original=np.asarray(image);clean=cleanup_text(original,38,subtitle=True)
  self.assertLess(np.count_nonzero(clean.mean(axis=2)<100),np.count_nonzero(original.mean(axis=2)<100)*.2)
 def test_ink_removal_has_clean_background_context(self):
  image=Image.new('RGB',(320,120),(145,155,165));draw=ImageDraw.Draw(image)
  draw.text((70,35),'TEST',font=ImageFont.truetype('/System/Library/Fonts/Supplemental/Arial Bold.ttf',38),fill='white',stroke_width=3,stroke_fill='black')
  original=np.asarray(image);clean=cleanup_text(original,38,subtitle=True,content_box=(60,30,230,85))
  self.assertLess(np.mean(np.abs(clean.astype(float)-np.array([145,155,165]))),1)
  self.assertTrue(np.array_equal(clean[:20],original[:20]))

 def test_off_center_partial_word_merges_into_full_caption(self):
  a=self.region(1,'Đơn giản',2.05,2.29);b=self.region(2,'Đơn giản hiệu quả',2.15,2.82)
  for sample in a['samples']:sample['box']=[.144,.402,.333,.118]
  for sample in b['samples']:sample['box']=[.160,.454,.633,.100]
  b['samples']*=2
  groups=consolidate_labels([a,b])
  self.assertEqual(len(groups),1)
  self.assertEqual(groups[0]['vi'],'Đơn giản hiệu quả')

 def test_white_letters_without_outline_on_bright_background(self):
  image=Image.new('RGB',(320,120),(190,195,200));draw=ImageDraw.Draw(image)
  draw.text((70,35),'TEST',font=ImageFont.truetype('/System/Library/Fonts/Supplemental/Arial Bold.ttf',38),fill='white')
  original=np.asarray(image);clean=cleanup_text(original,38,content_box=(60,30,230,85))
  self.assertLess(np.mean(np.abs(clean.astype(float)-np.array([190,195,200]))),.5)
