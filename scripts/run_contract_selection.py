"""Freeze and query a finite source-program portfolio for every campaign case."""
from __future__ import annotations

import argparse
from datetime import datetime,timezone
import fcntl
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from relation_search import contract_selection
from relation_search.checkpoint import digest,read
from relational_gap.provider import dispatch
from scripts.run_test_admission import _preload_local_imports,_loaded_sources,verify_seal


def frozen(path):
    return dict(path=str(Path(path).resolve()),sha256=digest(path))


def write(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    if path.exists():
        if read(path)!=value:raise ValueError('Immutable artifact differs: '+str(path))
        return
    with path.open('x') as stream:
        json.dump(value,stream,ensure_ascii=False,indent=2);stream.write('\n')


def prepare(args):
    output=args.output;output.mkdir(parents=True,exist_ok=False)
    _preload_local_imports(contract_selection)
    algorithm=_loaded_sources()
    cases=sorted({path.parents[2] for path in args.campaign.glob('*/round_*/prepared/candidates.json')})
    entries=[]
    for case in cases:
        paths=sorted(case.glob('round_*/prepared/candidates.json'))
        candidates={}
        for path in paths:
            for row in read(path)['candidates']:
                if not row.get('semantic_revision') and not row.get('is_source_profile'):
                    candidates.setdefault(row['id'],row)
        source=paths[0].parent
        corpus=read(source/'corpus.json')
        result=contract_selection.prepare(corpus,list(candidates.values()),(source/'issue.md').read_text(),
            budget=args.budget,max_prompt_bytes=args.max_prompt_bytes)
        request=result.pop('request')
        directory=output/case.name
        write(directory/'catalog.json',list(candidates.values()))
        write(directory/'analysis.json',result)
        write(directory/'request.json',request)
        entries.append(dict(case=case.name,source=str(source.resolve()),
            source_inputs={name:frozen(source/name) for name in ('corpus.json','frontend.json','case.json','selection.json','issue.md')},
            candidate_inputs=[frozen(path) for path in paths],catalog=frozen(directory/'catalog.json'),
            request=frozen(directory/'request.json'),presented=result['presented'],
            omitted=len(result['omitted']),total=result['total_candidates']))
        print(json.dumps(dict(case=case.name,presented=result['presented'],omitted=len(result['omitted']),
                              prompt_bytes=request['prompt_bytes'])),flush=True)
        del corpus
    verify_seal(algorithm)
    manifest=dict(version=contract_selection.VERSION,cases=entries,algorithm=algorithm,
        max_calls=args.max_calls,max_total_tokens=args.max_total_tokens,deadline_utc=args.deadline_utc,
        selection_budget=args.budget,source_pool='historical program-generated input candidates only',
        evaluation_labels_used=False,native_outcomes_sent_to_model=False)
    write(output/'prepared.json',manifest);write(output/'seal.json',frozen(output/'prepared.json'))
    return dict(cases=len(entries),presented=sum(row['presented'] for row in entries))


def run(args):
    root=args.input
    with (root/'.run.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        seal=read(root/'seal.json')
        if digest(seal['path'])!=seal['sha256']:raise ValueError('Prepared selection changed')
        prepared=read(root/'prepared.json');verify_seal(prepared['algorithm'])
        deadline=datetime.fromisoformat(prepared['deadline_utc'].replace('Z','+00:00'))
        calls=tokens=0;results=[]
        for row in prepared['cases']:
            directory=root/row['case']
            if digest(row['request']['path'])!=row['request']['sha256']:raise ValueError('Frozen request changed')
            request=read(row['request']['path']);reservation=request['prompt_bytes']+request['max_tokens']+1024
            if (directory/'completion/manifest.json').exists():
                receipt=read(directory/'completion/manifest.json')
                if receipt['status'] in {'prepared','dispatching'}:raise ValueError('Audit interrupted dispatch before resuming')
            else:
                if (calls>=prepared['max_calls'] or tokens+reservation>prepared['max_total_tokens']
                        or (deadline-datetime.now(timezone.utc)).total_seconds()<300):break
                receipt=dispatch(request,directory/'completion',root=ROOT)
            calls+=receipt['external_model_calls']
            usage=(receipt.get('usage') or {}).get('total_tokens')
            tokens+=usage if type(usage) is int and usage>=0 else reservation
            result=(contract_selection.validate(request,(directory/'completion/completion.txt').read_text(),
                    finish_reason=receipt.get('finish_reason')) if receipt['status']=='complete'
                    else dict(selected=[],error='provider_error'))
            write(directory/'selection.json',result)
            results.append(dict(case=row['case'],selection=frozen(directory/'selection.json'),
                                selected=len(result['selected']),error=result.get('error')))
            print(json.dumps(dict(case=row['case'],selected=len(result['selected']),calls=calls,tokens=tokens)),flush=True)
        summary=dict(cases=results,denominator=len(prepared['cases']),pending=len(prepared['cases'])-len(results),
                     provider_calls=calls,accounted_tokens=tokens,native_executions=0,ranking_only=True)
        write(root/'summary.json',summary)
        return {key:value for key,value in summary.items() if key!='cases'}


if __name__=='__main__':
    p=argparse.ArgumentParser(__doc__);p.add_argument('stage',choices=['prepare','run'])
    p.add_argument('--campaign',type=Path);p.add_argument('--input',type=Path);p.add_argument('--output',type=Path)
    p.add_argument('--budget',type=int,default=12);p.add_argument('--max-prompt-bytes',type=int,default=160000)
    p.add_argument('--max-calls',type=int,default=17);p.add_argument('--max-total-tokens',type=int,default=1600000)
    p.add_argument('--deadline-utc',default='2026-10-04T01:51:21Z')
    args=p.parse_args();print(json.dumps(prepare(args) if args.stage=='prepare' else run(args)))
