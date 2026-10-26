import tempfile
import unittest
from pathlib import Path
import numpy as np
import soundfile as sf
from local_dub.pipeline import command, FFMPEG, mix_and_mux, duration, tempo_filters

class LocalDubTests(unittest.TestCase):
    def test_incomplete_translation_is_rejected_before_voice_generation(self):
        from local_dub.translation_utils import parse_translations
        for value in [None, '{"segments":[]}', '{"segments":[{"id":0,"vi":null}]}']:
            with self.subTest(value=value), self.assertRaises(ValueError):
                parse_translations(value,[0])

    def test_tempo_chain_handles_long_speech(self):
        self.assertEqual(tempo_filters(5),'atempo=2,atempo=2,atempo=1.25000000')

    def test_overlong_voice_is_not_forced_into_short_slot(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'voice').mkdir()
            sf.write(root/'voice/0000.wav',np.ones(44100*4)*.1,44100)
            with self.assertRaisesRegex(RuntimeError,'vượt giới hạn 3'):
                mix_and_mux(root,[dict(start=0,end=1)],1,9,root/'log.txt')

    def test_cadence_target_never_allows_a_hidden_over_three_times_speedup(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'voice').mkdir();(root/'stems').mkdir()
            # Seven seconds can fit inside a three-second source window at 2.33x,
            # but it exceeds this line's planned two-second cadence at 3.5x.
            sf.write(root/'voice/0000.wav',np.ones(44100*7)*.1,44100)
            for name in ['bass','drums','other']:
                sf.write(root/'stems'/f'{name}.wav',np.zeros((44100*3,2)),44100)
            with self.assertRaisesRegex(RuntimeError,'vượt giới hạn 3'):
                mix_and_mux(root,[dict(start=0,end=3,target_duration=2,fit_end=3)],3,9,root/'log.txt')

    def test_omnivoice_is_not_given_a_hard_duration_cap(self):
        worker=(Path(__file__).parents[1]/'local_dub/voice_worker.py').read_text()
        self.assertNotIn("args['duration']",worker)

    def test_five_second_line_rejects_a_whole_paragraph(self):
        from local_dub.translation_utils import word_budget,validate_spoken_line
        self.assertGreaterEqual(word_budget(5.06),60)
        with self.assertRaises(ValueError):
            validate_spoken_line('Đổ chổi vào túi ni lông khi quét sàn sẽ dễ dàng vứt bỏ tóc. '*6,word_budget(5.06))
        self.assertEqual(validate_spoken_line('Bọc túi ni lông vào chổi để gom tóc.',word_budget(5.06)),'Bọc túi ni lông vào chổi để gom tóc.')

    def test_keeps_fuller_translation_when_it_fits_below_three_times(self):
        from local_dub.translation_utils import retime_word_budget,validate_spoken_line,word_budget
        text=' '.join(['từ']*50)
        self.assertEqual(validate_spoken_line(text,word_budget(5)),text)
        self.assertIsNone(retime_word_budget(text,5,12.5))
        shorter=retime_word_budget(text,5,16)
        self.assertGreaterEqual(shorter,28)
        self.assertLessEqual(shorter,32)

    def test_timeline_ducking_and_export(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); (root/'voice').mkdir(); (root/'stems').mkdir()
            sr=44100; total=4; t=np.arange(sr*total)/sr
            log=root/'process.log'
            command([FFMPEG,'-y','-f','lavfi','-i','color=black:s=160x240:r=25:d=4','-c:v','libx264','-pix_fmt','yuv420p',root/'source.mp4'],log)
            # A constant bed makes it possible to measure ducking independently of speech.
            bed=.1*np.sin(2*np.pi*250*t)
            for name in ['bass','drums','other','vocals']:
                wav=np.column_stack([bed,bed]) if name=='other' else np.zeros((len(t),2))
                if name=='vocals': wav[:]=.9  # Must never appear in the mixed output.
                sf.write(root/'stems'/f'{name}.wav',wav,sr,subtype='FLOAT')
            raw=.3*np.sin(2*np.pi*900*np.arange(sr*2)/sr)
            sf.write(root/'voice/0000.wav',raw,sr)
            lines=[dict(start=1,end=2)]
            result=mix_and_mux(root,lines,total,9,log)
            self.assertAlmostEqual(lines[0]['playback_speed'],2.0)
            voice,_=sf.read(root/'voice_vi.wav')
            self.assertLess(np.max(np.abs(voice[:sr])),1e-4)
            self.assertLess(np.max(np.abs(voice[2*sr:])),1e-4)
            self.assertGreater(np.max(np.abs(voice[sr:2*sr])),.1)
            mixed,_=sf.read(root/'mixed_vi.wav',always_2d=True)
            # Projection at bed frequency: lower under Vietnamese voice than in the opening gap.
            def bed_level(a,b):
                x=mixed[int(a*sr):int(b*sr),0]
                ts=np.arange(len(x))/sr
                return abs(np.sum(x*np.exp(-2j*np.pi*250*ts)))/len(x)
            self.assertLess(bed_level(1.3,1.8),bed_level(.2,.7)*.8)
            self.assertLess(abs(np.mean(mixed)),.01)
            self.assertLess(abs(duration(result)-total),.1)

if __name__=='__main__': unittest.main()
