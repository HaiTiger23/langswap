"""Build sentence anchors from measured source-word times, never proportional text timing."""
import re


def speech_tokens(text):
    return re.findall(r"[^\W_]+(?:['’][^\W_]+)?",text.casefold(),flags=re.UNICODE)


def anchors_from_words(words,block_id,start,end):
    chunks=[];pending=[]
    def flush():
        if not pending:return
        first=max(start,float(pending[0]['start']))
        last=min(end,float(pending[-1]['end']))
        if last<=first:raise ValueError('Không căn được thời gian câu gốc; cần kiểm tra transcript.')
        chunks.append(dict(block_id=block_id,start=round(first,3),end=round(last,3),zh=''.join(w['word'] for w in pending).strip(),source='forced_alignment'))
        pending.clear()
    for i,word in enumerate(words):
        if not word['word'].strip():continue
        pending.append(word)
        span=float(word['end'])-float(pending[0]['start'])
        gap=float(words[i+1]['start'])-float(word['end']) if i+1<len(words) else 0
        if span>=1.2 and (re.search(r'[，。！？,!?;；：:]$',word['word']) or gap>=.25 or span>=3.5):flush()
    if pending:
        # Do not create a tiny final syllable when it belongs to the previous sentence.
        if chunks and float(pending[-1]['end'])-float(pending[0]['start'])<.7 and float(pending[0]['start'])-chunks[-1]['end']<.2:
            chunks[-1]['zh']+=''.join(w['word'] for w in pending)
            chunks[-1]['end']=round(min(end,float(pending[-1]['end'])),3)
        else:flush()
    if not chunks:raise ValueError('Không tìm được mốc câu từ lời Trung gốc.')
    return chunks


def validate_partition(result,anchors,blocks):
    """Partitioning may change punctuation, but must keep all translated words in order."""
    for i,block in enumerate(blocks):
        joined=' '.join(result[j] for j,a in enumerate(anchors) if a['block_id']==i)
        if speech_tokens(joined)!=speech_tokens(block['vi']):
            raise ValueError(f'Chia câu làm mất/thêm/đổi lời dịch ở đoạn {i+1}; chỉ được chia nguyên văn bản dịch đã có.')
