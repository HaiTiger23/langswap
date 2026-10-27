import unittest
import numpy as np
from local_dub.screen_text import track_text,sample_box,pixel_box,text_tile,dialogue_subtitle,MAX_AGY_SCREEN_REGIONS

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
 def test_spoken_caption_is_classified_locally_before_asking_agy(self):
  track=dict(text='水垢直接就分解了',start=4.0,end=5.0)
  dialogue=[dict(start=3.8,end=5.2,zh='水垢直接就分解了')]
  self.assertTrue(dialogue_subtitle(track,dialogue))
  self.assertLess(MAX_AGY_SCREEN_REGIONS,100)

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

class ScreenPerformanceSafetyTests(unittest.TestCase):
 def test_model_batches_are_bounded_without_dropping_any_region(self):
  import tempfile,json
  from pathlib import Path
  from unittest.mock import patch
  import local_dub.screen_text as screen
  tracks=[dict(id=i,text='清洁油壶',start=i,end=i+1,confidence=1,samples=[dict(time=i,box=[.1,.2,.3,.1])]*3) for i in range(183)]
  calls=[]
  def classify(batch,segments,work,translate_subtitles):
   calls.append(len(batch))
   return [track|dict(kind='label',vi='Vệ sinh chai dầu') for track in batch]
  with tempfile.TemporaryDirectory() as folder,patch.object(screen,'_classify_chunk',side_effect=classify):
   result=screen.classify_translate(tracks,[],folder)
   self.assertEqual([track['id'] for track in result],list(range(183)))
   self.assertTrue(all(track['vi'] for track in result))
   self.assertEqual(calls,[80,80,23])
   self.assertEqual(json.loads((Path(folder)/'classification_stats.json').read_text())['completed_batches'],3)
 def test_frame_stream_handles_arbitrary_read_boundaries_and_truncation(self):
  from local_dub.screen_text import jpeg_frames
  class Chunks:
   def __init__(self,chunks):self.chunks=iter(chunks)
   def read(self,_):return next(self.chunks,b'')
  self.assertEqual(list(jpeg_frames(Chunks([b'\xff',b'\xd8abc\xff',b'\xd9\xff\xd8def\xff\xd9']))),[b'\xff\xd8abc\xff\xd9',b'\xff\xd8def\xff\xd9'])
  with self.assertRaisesRegex(RuntimeError,'giữa frame'):
   list(jpeg_frames(Chunks([b'\xff\xd8abc'])))
 def test_timeline_matches_full_scan_and_keeps_paint_order(self):
  from local_dub.screen_text import RegionTimeline
  regions=[dict(start=2,end=4,id=0),dict(start=0,end=3,id=1),dict(start=1,end=2,id=2)]
  timeline=RegionTimeline(regions)
  for t in (0,.5,1,1.99,2,3,4,10):
   self.assertEqual(timeline.at(t),[r for r in regions if r['start']<=t<r['end']])
 def test_binary_sample_lookup_preserves_original_union(self):
  samples=[dict(time=round(i/30,3),box=[.1+(i%3)*.01,.2,.3,.1]) for i in range(180)]
  track=dict(samples=samples)
  for t in np.arange(-.2,6.2,.017):
   nearest=min(samples,key=lambda s:abs(s['time']-t))
   if abs(nearest['time']-t)>1/30+.065:
    self.assertIsNone(sample_box(track,t));continue
   boxes=[s['box'] for s in samples if abs(s['time']-nearest['time'])<=1/30+.01]
   x=min(b[0] for b in boxes);y=min(b[1] for b in boxes)
   expected=[x,y,max(b[0]+b[2] for b in boxes)-x,max(b[1]+b[3] for b in boxes)-y]
   np.testing.assert_allclose(sample_box(track,t),expected)

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
