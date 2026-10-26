"""One speaking cadence per video; source starts remain fixed, small pauses may lend space."""
import math
from local_dub.translation_utils import syllables

BASE_SPS=4.8
MAX_TARGET_SPS=7.0
PACE_TOLERANCE=.12
SILENCE_PAD=.12


def plan_pacing(segments,total):
    counts=[max(1,syllables(s['vi'])) for s in segments]
    windows=[]
    for i,s in enumerate(segments):
        start=float(s['start']);end=float(s['end'])
        next_start=float(segments[i+1]['start']) if i+1<len(segments) else total
        # Do not start early or consume an entire dramatic pause. At most 250 ms
        # after the original line, leaving 80 ms before the next source start.
        available_end=min(total,end+.25,max(end,next_start-.08))
        available_end=min(available_end,next_start)
        if available_end<=start:raise ValueError(f'Mốc thời gian không hợp lệ ở câu {i+1}')
        windows.append(available_end-start)
    # A weighted 75th percentile avoids letting one overlong sentence accelerate
    # the entire story. Weight by speech length so interjections do not dominate.
    densities=sorted((n/max(.18,w-SILENCE_PAD),n) for n,w in zip(counts,windows))
    cutoff=sum(counts)*.75;acc=0;target=BASE_SPS
    for density,weight in densities:
        acc+=weight
        if acc>=cutoff:target=min(MAX_TARGET_SPS,max(BASE_SPS,density));break
    requests={};plans=[]
    for i,(s,n,window) in enumerate(zip(segments,counts,windows)):
        capacity=max(.18,window-SILENCE_PAD)
        fastest=target*(1+PACE_TOLERANCE)
        if n/capacity>fastest+1e-6:
            requests[str(i)]=dict(budget=max(1,math.floor(capacity*target)),actual=None,target_sps=round(target,3),available_seconds=round(window,3),reason='uneven_pacing')
        desired=max(.42,n/target+SILENCE_PAD)
        duration=min(window,desired)
        plan=dict(target_sps=round(target,4),target_duration=round(duration,4),fit_end=round(float(s['start'])+window,4),syllables=n,expected_sps=round(n/max(.18,duration-SILENCE_PAD),4))
        plans.append(plan)
    return dict(target_sps=round(target,4),tolerance=PACE_TOLERANCE,plans=plans,rewrite_requests=requests)
