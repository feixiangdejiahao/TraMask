"""Restore the formal cohort through the final trajectory action, without LLM calls."""
from concurrent.futures import ThreadPoolExecutor, as_completed
import argparse
from pathlib import Path
import sys
import traceback

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from tramask_pilot.corpus import RUN,read,write
from tramask_pilot.submission_replay import OUTPUT,replay_submission

def main():
    parser=argparse.ArgumentParser(__doc__)
    parser.add_argument('--case',action='append')
    parser.add_argument('--formal-cohort',action='store_true')
    parser.add_argument('--workers',type=int,default=4)
    args=parser.parse_args()
    if bool(args.case)==args.formal_cohort:
        parser.error('Specify either --case or --formal-cohort')
    cases=sum([read(RUN/f'formal_{k}_cohort.json')['cases'] for k in ('failed','successful')],[])
    if args.case:
        cases=[c for c in cases if c['id'] in args.case]
        if len(cases)!=len(set(args.case)):parser.error('Unknown formal case')
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        pending={pool.submit(replay_submission,c):c for c in cases}
        for future in as_completed(pending):
            c=pending[future]
            try:
                r=future.result()
                print(c['id'],'finished',str(r['validation'])[:250],flush=True)
            except Exception as exc:
                write(OUTPUT/c['id']/'error.json',{'type':type(exc).__name__,'message':str(exc),'traceback':traceback.format_exc()})
                print(c['id'],'ERROR',str(exc),flush=True)

if __name__=='__main__':main()
