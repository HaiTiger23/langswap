"""Translate globally first; partition the saved Vietnamese translation only afterwards."""
import json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from local_dub.agy_translation import translate
from local_dub.translation_utils import word_budget

work=Path(sys.argv[1]);retiming='--retime' in sys.argv;partition='--partition' in sys.argv
blocks=json.loads((work/'translated_blocks.json').read_text()) if (work/'translated_blocks.json').exists() else None
if not retiming and not partition and blocks is not None:
    print('Dùng lại bản dịch toàn bộ đã lưu.',flush=True);sys.exit(0)
filename='segments.json' if retiming else 'sentence_anchors.json' if partition else 'transcript.json'
segments=json.loads((work/filename).read_text())
requests=json.loads((work/'retime_request.json').read_text()) if retiming else {}
glossary=json.loads((Path(__file__).parent/'glossary.json').read_text())
context=''.join(s['zh'] for s in segments)
terms={zh:vi for zh,vi in glossary.items() if zh in context}
rows=[]
for i,s in enumerate(segments):
    window=max(.1,min(s['end'],segments[i+1]['start'] if i+1<len(segments) else s['end'])-s['start'])
    budget=10000 if partition else int(requests[str(i)]['budget']) if str(i) in requests else word_budget(window)
    row=dict(id=i,start=s['start'],end=s['end'],source_zh=s['zh'],max_vi_syllables=budget)
    if partition:row['block_id']=s['block_id']
    if retiming:row.update(previous_vi=s['vi'],actual_audio_seconds=requests.get(str(i),{}).get('actual'),target_sps=requests.get(str(i),{}).get('target_sps'),available_seconds=requests.get(str(i),{}).get('available_seconds'))
    rows.append(row)
expected=[int(i) for i in requests] if retiming else list(range(len(segments)))
print(('Chia nguyên văn bản dịch đã chốt vào các mốc câu gốc.' if partition else f'agy đang đọc toàn bộ {len(segments)} đoạn Trung trong một lượt; '+('kèm ảnh 12 frame.' if (work/'storyboard_4x3.jpg').exists() else 'chỉ gửi văn bản.')),flush=True)
result=translate(rows,terms,work,expected,retiming,partition_blocks=blocks if partition else None)
for i,vi in result.items():
    segments[i]['vi']=vi;segments[i]['word_budget']=word_budget(segments[i]['end']-segments[i]['start']) if partition else rows[i]['max_vi_syllables']
    print(f'Câu {i+1}/{len(segments)}: {vi}',flush=True)
dest=work/('segments.json' if retiming or partition else 'translated_blocks.json')
tmp=dest.with_suffix('.tmp');tmp.write_text(json.dumps(segments,ensure_ascii=False,indent=2));tmp.replace(dest)
