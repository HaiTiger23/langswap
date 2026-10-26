import argparse
import json
from .pipeline import run

parser=argparse.ArgumentParser(description='Lồng tiếng video Trung → Việt bằng OmniVoice trên Mac')
parser.add_argument('video')
parser.add_argument('--reference')
parser.add_argument('--reference-text',default='')
parser.add_argument('--duck-db',type=float,default=9)
parser.add_argument('--steps',type=int,choices=[16,32],default=16)
args=parser.parse_args()
print(json.dumps(run(args.video,args.reference,args.reference_text,args.duck_db,args.steps,emit=lambda p,m:print(m,flush=True)),ensure_ascii=False,indent=2))
