import unittest
import numpy as np
from local_dub.screen_text import track_text,sample_box,pixel_box,text_tile

class ScreenTextTests(unittest.TestCase):
 def test_no_chinese_does_not_create_blur_regions(self):
  self.assertEqual(track_text([{'lines':[dict(text='Kitchen',confidence=.99,x=.2,y=.1,width=.3,height=.05)]}]*4,1),[])
 def test_fleeting_chinese_still_gets_a_mask(self):
  self.assertEqual(len(track_text([{'lines':[dict(text='中文',confidence=.99,x=.2,y=.1,width=.3,height=.05)]}],1)),1)
 def test_tracks_stop_across_scene_changes_and_missing_detections(self):
  line=dict(text='干净',confidence=.99,x=.2,y=.1,width=.3,height=.05)
  frames=[dict(lines=[line]),dict(lines=[line])]+[dict(lines=[]) for _ in range(24)]+[dict(lines=[line]),dict(lines=[line])]
  tracks=track_text(frames,2)
  self.assertEqual(len(tracks),2)
  self.assertLess(tracks[0]['end'],tracks[1]['start'])
  self.assertIsNone(sample_box(tracks[0],1))
 def test_native_vision_coordinates_are_flipped_and_clipped(self):
  line=dict(text='字幕',confidence=.99,x=.2,y=.1,width=.3,height=.05)
  tr=track_text([dict(lines=[line])]*2,1)[0]
  self.assertAlmostEqual(tr['samples'][0]['box'][1],.85)
  self.assertEqual(pixel_box([-.1,-.1,1.3,1.3],100,200),(0,0,100,200))
 def test_low_confidence_real_subtitle_is_still_masked(self):
  line=dict(text='轻轻一擦',confidence=.3,x=.2,y=.1,width=.3,height=.05)
  tracks=track_text([dict(lines=[line])]*3,1)
  self.assertEqual(len(tracks),1)
  self.assertTrue(tracks[0]['mask_only'])
 def test_box_union_covers_both_extremes_of_animated_text(self):
  tr=dict(samples=[dict(time=.5,box=[.2,.2,.2,.1]),dict(time=.58,box=[.15,.15,.35,.2])])
  box=sample_box(tr,.54)
  self.assertLessEqual(box[0],.15)
  self.assertGreaterEqual(box[0]+box[2],.5)
 def test_vietnamese_accents_render_in_small_label(self):
  tile=text_tile('Nước rửa chén',240,70)
  self.assertEqual(tile.size,(240,70))
  self.assertGreater(np.asarray(tile)[:,:,:3].max(),200)

class SavedScreenJobTests(unittest.TestCase):
 def test_screen_action_reuses_saved_audio_and_original_source(self):
  import tempfile
  from pathlib import Path
  from unittest.mock import Mock,patch
  import studio_server as studio
  with tempfile.TemporaryDirectory() as folder:
   root=Path(folder);source=root/'original.mp4';source.touch();(root/'mixed_vi.wav').touch()
   old=dict(id='old',status='done',name='Saved',args=dict(video=str(source)),result=dict(directory=str(root)))
   store=Mock();store.get.return_value=old
   store.enqueue.side_effect=lambda name,args,fp:(dict(id='new',status='queued',args=args),False)
   runner=Mock()
   with patch.object(studio,'STORE',store),patch.object(studio,'RUNNER',runner),patch.object(studio,'fingerprint',return_value='test'):
    result=studio.screen_job('old',text_mode='subtitles')
   args=store.enqueue.call_args.args[1]
   self.assertEqual(args['video'],str(source))
   self.assertEqual(args['reuse_dub_directory'],str(root))
   self.assertEqual(args['text_mode'],'subtitles')
   self.assertEqual(result['status'],'queued')
   runner.notify.assert_called_once()

class ScreenQualityGateTests(unittest.TestCase):
 def test_residual_chinese_is_masked_and_rechecked(self):
  import tempfile,json
  from pathlib import Path
  from unittest.mock import patch
  import local_dub.screen_text as screen
  leak=dict(id=1,text='水龙头',confidence=.3,start=1,end=2,samples=[dict(time=1.2,box=[.2,.2,.2,.1])])
  with tempfile.TemporaryDirectory() as folder:
   with patch.object(screen,'detect',side_effect=[[],[leak],[]]),patch.object(screen,'classify_translate',return_value=[]),patch.object(screen,'render') as render,patch('local_dub.pipeline.duration',return_value=15):
    out=screen.process('video','audio',[],folder,15,'all',lambda *a:None,lambda *a:None)
   self.assertEqual(render.call_count,2)
   self.assertIn('checked',out.name)
   self.assertEqual(json.loads((Path(folder)/'screen_qc.json').read_text())[-1]['remaining'],[])
 def test_known_residual_cannot_be_marked_complete(self):
  import tempfile
  from unittest.mock import patch
  import local_dub.screen_text as screen
  leak=dict(id=1,text='中文',confidence=1,start=1,end=2,samples=[dict(time=1.2,box=[.2,.2,.2,.1])])
  with tempfile.TemporaryDirectory() as folder:
   with patch.object(screen,'detect',side_effect=[[],[leak],[leak],[leak]]),patch.object(screen,'classify_translate',return_value=[]),patch.object(screen,'render'),patch('local_dub.pipeline.duration',return_value=15),self.assertRaisesRegex(RuntimeError,'chưa đánh dấu hoàn tất'):
    screen.process('video','audio',[],folder,15,'all',lambda *a:None,lambda *a:None)
