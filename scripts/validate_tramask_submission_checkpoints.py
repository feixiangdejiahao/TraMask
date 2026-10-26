"""Independently validate completed frozen submission checkpoints (no subject replay)."""
from concurrent.futures import ThreadPoolExecutor,as_completed
from pathlib import Path
import argparse
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from tramask_pilot.corpus import RUN,read,write,receipt
from tramask_pilot.runtime import Container
from tramask_pilot.submission_replay import OUTPUT
from tramask_pilot.submission_state import validate_submission_state

def validate(case):
    directory=OUTPUT/case['id']
    report=directory/'validation_v03/report.json'
    if report.exists():return read(report)
    summary=read(directory/'summary.json')
    checkpoint=summary['checkpoint']
    with Container(checkpoint['image_id'],directory/'independent_validation_v03',checkpoint['head']) as runtime:
        result=validate_submission_state(runtime,RUN/'inputs'/case['id']/'model.patch',
            directory/'validation_v03',base_commit=case['base_commit'])
        write(directory/'validation_v03/provenance.json',{
            'source_checkpoint':checkpoint,'code':receipt(ROOT/'src/tramask_pilot/submission_state.py'),
            'original_summary':receipt(directory/'summary.json'),
            'original_terminal_evidence':receipt(RUN/'submission_state_audit/original_terminal_authority.json'),
            'scope':'Read-only verification of the frozen checkpoint in a new container, no repair or subject commands.'})
        return result

def main():
    parser=argparse.ArgumentParser(__doc__)
    parser.add_argument('--workers',type=int,default=4)
    args=parser.parse_args()
    cases=sum([read(RUN/f'formal_{k}_cohort.json')['cases'] for k in ('failed','successful')],[])
    completed=[c for c in cases if (OUTPUT/c['id']/'summary.json').exists()]
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures={pool.submit(validate,c):c for c in completed}
        for f in as_completed(futures):
            c=futures[f]
            try:
                r=f.result();print(c['id'],r['submission_state_status'],len(r['mismatches']),flush=True)
            except Exception as exc:print(c['id'],'ERROR',type(exc).__name__,str(exc),flush=True)

if __name__=='__main__':main()
