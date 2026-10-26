"""Execute completed diagnostic outputs only. Gold runs are explicit evaluation."""
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import argparse
import json
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src'),str(ROOT)]
from scripts.run_augmentation_diagnostic6 import RUN,OLD,read,write,execute_one
from combination_testing.runner import run_artifact,compare_pair


def gold(cid,arm,round_number):
    directory=RUN/'cases'/cid/arm/f'round{round_number}'/'execution'
    result_path=directory/'comparison.json'
    if result_path.exists():return read(result_path)
    case=next(c for c in read(RUN/'cases.json') if c['id']==cid)
    case['base_commit']=read(OLD/'cases'/cid/'repository_provenance.json')['base_commit']
    ref=directory/'gold/result.json'
    reference=read(ref) if ref.exists() else run_artifact(directory/'artifact','reference',directory/'gold',
        reference_patch=OLD/'gold_comparison_v1/cases'/cid/'gold.patch',registry=[case])
    result=compare_pair(read(directory/'candidate/result.json'),reference)
    result.update(case=cid,arm=arm,round=round_number,evaluation_only=True)
    write(result_path,result)
    return {k:v for k,v in result.items() if k!='tests'}


def main():
    global RUN
    p=argparse.ArgumentParser(__doc__);p.add_argument('--stage',choices=['candidate','gold'],default='candidate')
    p.add_argument('--case',action='append');p.add_argument('--arm',action='append');p.add_argument('--round',type=int);p.add_argument('--workers',type=int,default=3)
    p.add_argument('--budget-recovery',action='store_true')
    a=p.parse_args()
    if a.budget_recovery:
        from scripts import run_augmentation_diagnostic6 as diagnostic
        RUN=RUN/'budget_recovery'
        diagnostic.RUN=RUN
    if a.stage=='gold' and not a.case:raise ValueError('Gold requires explicit case selection after portability review')
    jobs=[]
    for path in sorted(RUN.glob('cases/*/*/round*/assessment.json')):
        directory=path.parent;cid=directory.parent.parent.name;arm=directory.parent.name;rn=int(directory.name[5:])
        if a.case and cid not in a.case or a.arm and arm not in a.arm or a.round and rn!=a.round:continue
        if read(path)['decision']!='gap':continue
        result=directory/'execution'/('feedback.json' if a.stage=='candidate' else 'comparison.json')
        if result.exists():continue
        if a.stage=='gold' and not (directory/'execution/candidate/result.json').exists():continue
        jobs.append((cid,arm,rn))
    print(json.dumps({'stage':a.stage,'ready_jobs':jobs}),flush=True)
    function=execute_one if a.stage=='candidate' else gold
    with ThreadPoolExecutor(max_workers=a.workers) as pool:
        for f in as_completed([pool.submit(function,*j) for j in jobs]):print(json.dumps(f.result(),ensure_ascii=False),flush=True)


if __name__=='__main__':main()
