import os
import sys
from pathlib import Path
os.environ['TORCH_HOME'] = str(Path(__file__).resolve().parents[1] / 'models_weights')
from langswap.ml.text_to_speech_service.demucs_client import DemucsClient
out=Path(sys.argv[2]); out.mkdir(parents=True,exist_ok=True)
# Incomplete attempts are rerun, never mistaken for a completed separation.
for name in ['vocals','bass','drums','other']:
    (out/f'{name}.wav').unlink(missing_ok=True)
DemucsClient().separate(sys.argv[1],str(out))
