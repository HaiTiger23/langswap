"""Local Chinese ASR on the original audio, independent of Demucs artifacts."""
import sys,json,os
from pathlib import Path
from mlx_audio.stt.utils import load_model
from huggingface_hub import snapshot_download

work=Path(sys.argv[1])
model_id=os.getenv('DUB_ASR_MODEL','mlx-community/Qwen3-ASR-1.7B-4bit')
try:
    model_path=snapshot_download(model_id,local_files_only=True,allow_patterns=['*.json','*.safetensors','*.txt','*.model','*.tiktoken'])
except Exception:model_path=model_id
print('Đang nhận diện tiếng Trung bằng Qwen3-ASR trên âm thanh gốc.',flush=True)
model=load_model(model_path)
result=model.generate(str(work/'asr_original_16k.wav'),language='Chinese',max_tokens=8192,chunk_duration=12,temperature=0,verbose=False)
rows=[dict(start=float(s['start']),end=float(s['end']),zh=s['text'].strip(),source='qwen_asr') for s in result.segments if s['text'].strip()]
if not rows:raise RuntimeError('Không nhận diện được tiếng Trung đáng tin cậy.')
tmp=work/'transcript.tmp';tmp.write_text(json.dumps(rows,ensure_ascii=False,indent=2));tmp.replace(work/'transcript.json')
print(f'Đã nhận diện {len(rows)} đoạn tiếng Trung.',flush=True)
