"""Force-align the recognized Chinese text with cached Whisper; do not retranscribe it."""
import sys,json,os
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import numpy as np
import soundfile as sf
from faster_whisper import WhisperModel
from faster_whisper.tokenizer import Tokenizer
from faster_whisper.audio import pad_or_trim
from local_dub.sentence_alignment import anchors_from_words

work=Path(sys.argv[1]);root=Path(__file__).resolve().parents[1]
blocks=json.loads((work/'translated_blocks.json').read_text())
audio,sr=sf.read(work/'alignment_16k.wav',dtype='float32')
model=WhisperModel(os.getenv('DUB_ALIGNMENT_MODEL','large-v3'),device='cpu',compute_type='int8',cpu_threads=4,download_root=str(root/'models_weights'),local_files_only=True)
tokenizer=Tokenizer(model.hf_tokenizer,model.model.is_multilingual,task='transcribe',language='zh')
anchors=[];audit=[]
for i,b in enumerate(blocks):
 start=max(0,float(b['start']));end=min(len(audio)/sr,float(b['end']))
 if end-start>28:raise RuntimeError('Đoạn nhận diện dài quá 28 giây; chưa có mốc câu đủ tin cậy để căn.')
 clip=audio[round(start*sr):round(end*sr)]
 features=model.feature_extractor(clip)
 n=min(features.shape[-1],model.feature_extractor.nb_max_frames)
 features=pad_or_trim(features,model.feature_extractor.nb_max_frames)
 tokens=tokenizer.encode(b['zh'])
 aligned=model.find_alignment(tokenizer,[tokens],model.encode(features),n)[0]
 words=[dict(word=w['word'],start=start+float(w['start']),end=start+float(w['end'])) for w in aligned]
 # DTW must cover supplied text and remain monotonic. Never invent proportional timestamps.
 if ''.join(w['word'] for w in words).strip()!=b['zh'].strip():raise RuntimeError('Bộ căn mốc chưa bao phủ đủ lời Trung.')
 last=start
 for w in words:
  if w['start']<last-.03 or w['end']<w['start'] or w['end']>end+.1:raise RuntimeError('Mốc từ gốc không hợp lệ; chưa xuất giọng sai nhịp.')
  last=w['end']
 anchors.extend(anchors_from_words(words,i,start,end));audit.append(dict(block_id=i,words=words))
 print(f'Đã căn lời Trung đoạn {i+1}/{len(blocks)} theo âm thanh gốc.',flush=True)
(work/'source_word_alignment.json').write_text(json.dumps(audit,ensure_ascii=False,indent=2))
tmp=work/'sentence_anchors.tmp';tmp.write_text(json.dumps(anchors,ensure_ascii=False,indent=2));tmp.replace(work/'sentence_anchors.json')
