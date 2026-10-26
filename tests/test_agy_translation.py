import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from subprocess import CompletedProcess
from local_dub.agy_translation import translate, decode_result, cli_error

class AgyTranslationTests(unittest.TestCase):
    def test_numeric_ids_are_validated_locally_without_gemini_enum(self):
        envelope=json.dumps(dict(status='SUCCESS',num_turns=1,structured_output={'segments':[{'id':0,'vi':'Chị ơi!'}]}))
        with tempfile.TemporaryDirectory() as folder:
            work=Path(folder)/'data'/'job';work.mkdir(parents=True)
            def fake(args,**kwargs):
                schema=json.loads((work/'agy_schema.json').read_text())
                self.assertEqual(schema['properties']['segments']['items']['properties']['id'],{'type':'integer'})
                return CompletedProcess(args,0,envelope,'')
            with patch('local_dub.agy_translation.subprocess.run',side_effect=fake):
                self.assertEqual(translate([dict(id=0,source_zh='姐啊',max_vi_syllables=8)],{},work),{0:'Chị ơi!'})
    def test_image_viewing_turn_is_accepted_only_with_storyboard(self):
        envelope=json.dumps(dict(status='SUCCESS',num_turns=2,structured_output={'segments':[{'id':0,'vi':'Chị ơi'}]}))
        with self.assertRaises(ValueError):decode_result(envelope,[0],{0:8})
        self.assertEqual(decode_result(envelope,[0],{0:8},allow_image=True)[0],{0:'Chị ơi'})

    def test_wrong_duplicate_and_missing_ids_rejected(self):
        for rows in [[{'id':9,'vi':'Chào'}],[{'id':0,'vi':'Chào'},{'id':0,'vi':'Chào'}],[]]:
            with self.subTest(rows=rows),self.assertRaises(ValueError):
                decode_result(json.dumps(dict(status='SUCCESS',structured_output={'segments':rows})),[0],{0:10})
    def test_exit_error_keeps_actual_cause(self):
        message=cli_error(json.dumps(dict(status='ERROR',error='INVALID_ARGUMENT: id enum cannot be empty')),'warning: noise',3)
        self.assertIn('INVALID_ARGUMENT',message)
        self.assertNotIn('đăng nhập',message)
    def test_non_json_error_fallback(self):
        self.assertIn('connection refused',cli_error('','warning: ignored\nconnection refused',3))

if __name__=='__main__':unittest.main()
