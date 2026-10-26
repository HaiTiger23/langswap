"""Runs in the existing OmniVoice environment, independently of Langswap's torch."""
import json
import os
import sys
import shutil
from pathlib import Path

import numpy as np
import soundfile as sf
import torch
from omnivoice import OmniVoice

job = json.loads(Path(sys.argv[1]).read_text())
root = Path(job['directory'])
print(json.dumps({'status': 'loading', 'message': 'Đang nạp OmniVoice trên Apple Silicon…'}, ensure_ascii=False), flush=True)
device = 'mps' if torch.backends.mps.is_available() else 'cpu'
model = OmniVoice.from_pretrained(job['model'], device_map=device, dtype=torch.float16 if device == 'mps' else torch.float32)
ref = job.get('reference') or None
ref_text = job.get('reference_text') or None
fixed_ref=root/'voice_reference.wav'
fixed_text=root/'voice_reference.txt'
if not ref and fixed_ref.exists() and fixed_text.exists():
    ref,ref_text=str(fixed_ref),fixed_text.read_text()
for i, seg in enumerate(job['segments']):
    dest = root / 'voice' / f'{i:04d}.wav'
    if not dest.exists():
        args = dict(text=seg['vi'], language='vi', num_step=job.get('steps', 16))
        # Never force OmniVoice to an exact duration. Its duration argument fixes
        # the number of generated audio tokens, which can truncate the final word
        # when Vietnamese needs more room. Generate the complete utterance first;
        # the pipeline then measures it, uses pitch-preserving atempo (<= 3x), and
        # asks for a shorter rewrite if it still cannot fit.
        if ref:
            args.update(ref_audio=ref, ref_text=ref_text)
        with torch.inference_mode():
            wav = model.generate(**args)[0]
        wav = np.asarray(wav, dtype=np.float32).squeeze()
        if not np.isfinite(wav).all() or not wav.size or np.max(np.abs(wav)) < 1e-5:
            raise RuntimeError(f'OmniVoice tạo âm thanh rỗng ở câu {i+1}')
        temporary = dest.with_suffix('.partial.wav')
        sf.write(str(temporary), wav, model.sampling_rate)
        temporary.replace(dest)
    # Reuse the first Vietnamese output to keep one voice across the video.
    if not ref:
        shutil.copy2(dest,fixed_ref)
        fixed_text.write_text(seg['vi'])
        ref, ref_text = str(fixed_ref), seg['vi']
    print(json.dumps({'status': 'segment', 'done': i+1, 'total': len(job['segments'])}, ensure_ascii=False), flush=True)
print(json.dumps({'status': 'done'}), flush=True)
