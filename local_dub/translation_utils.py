import json
import re
from local_dub.timing_policy import NATURAL_SYLLABLES_PER_SECOND, MAX_SPEED, PREFERRED_SPEED


def parse_translations(text,expected_ids):
    if not isinstance(text, str):
        raise ValueError('Model chưa trả về bản dịch dạng văn bản.')
    text=re.sub(r'^```(?:json)?\s*|\s*```$','',text.strip())
    value=json.loads(text)
    items=value['segments'] if isinstance(value,dict) else value
    result={}
    for item in items:
        idx=item['id']
        if not isinstance(item.get('vi'), str):
            raise ValueError('Model trả bản dịch rỗng hoặc không phải văn bản.')
        vi=item['vi'].strip()
        if type(idx) is not int or idx in result or not vi or re.search(r'[\u3400-\u9fff]',vi):
            raise ValueError('Bản dịch trùng id, rỗng hoặc còn chữ Trung.')
        result[idx]=vi
    if set(result)!=set(expected_ids):
        raise ValueError('Model dịch trả thiếu/thừa câu; cần thử lại.')
    return result


def syllables(text):
    return len(re.findall(r"[^\W_]+(?:['’][^\W_]+)?", text, flags=re.UNICODE))


def word_budget(seconds,rate=NATURAL_SYLLABLES_PER_SECOND,speed=MAX_SPEED):
    return max(1,int(max(0,float(seconds))*rate*speed))


def validate_spoken_line(text,budget):
    if not isinstance(text,str) or not text.strip():raise ValueError('Bản dịch rỗng.')
    text=text.strip().strip('"“”')
    text=re.sub(r'^(?:Bản dịch|Dịch|Tiếng Việt)\s*:\s*','',text,flags=re.I)
    if re.search(r'[\u3400-\u9fff{}\[\]]',text):raise ValueError('Bản dịch phải chỉ gồm lời tiếng Việt.')
    count=syllables(text)
    if count>budget:raise ValueError(f'Câu có {count} âm tiết, chỉ được tối đa {budget}.')
    if not count:raise ValueError('Bản dịch không có lời đọc.')
    return text


def retime_word_budget(text,seconds,actual):
    if actual<=seconds*MAX_SPEED:
        return None
    count=syllables(text)
    return max(1,min(count-1,int(count*seconds*PREFERRED_SPEED/actual*.95),word_budget(seconds)))
