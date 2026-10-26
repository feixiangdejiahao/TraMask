"""One uniform final-response retry for primary technical unknowns.

This is a separately reported supplement. It never changes primary results,
candidate selection, source evidence, reference labels or tests.
"""
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src'),str(ROOT)]
from augmentation.detection import parse_decision
from augmentation.pipeline import write_json
from augmentation.provider import dispatch
from scripts.run_augmentation_detection30_v3 import check_protocol

RUN=ROOT/'experiments/relation_distinction/results/pilot30_v3_detection_20261009_v1'
OUT=RUN/'decision_recovery_v1'


def read(path):
    return json.loads(Path(path).read_text())


def receipt(path):
    return {'path':str(Path(path).resolve()),'sha256':hashlib.sha256(Path(path).read_bytes()).hexdigest()}


def initialize():
    check_protocol()
    assert len(list(RUN.glob('cases/*/detection.json')))==30
    OUT.mkdir(exist_ok=False)
    eligible=[]
    for path in sorted(RUN.glob('cases/*/detector/*/result.json')):
        d=read(path)
        if d['decision']!='unknown' or d['stop_reason'] not in {'action_error','provider_incomplete'}:
            continue
        request=path.parent/f'round{d["rounds"]}'/'request.json'
        payload=read(request)
        prompt=json.loads(payload['messages'][-1]['content'])
        assert prompt['remaining_calls']==1, request
        eligible.append({'case':path.parts[-4],'candidate':d['candidate_id'],
                         'primary_result':receipt(path),'request':receipt(request),
                         'primary_stop':d['stop_reason']})
    write_json(OUT/'protocol.json',{'created_at':datetime.now(timezone.utc).isoformat(),
      'selection':'All primary unknowns ending in action_error or provider_incomplete; no semantic label selection.',
      'same_input':True,'input_rule':'Reuse the exact final primary system and user messages. Only max_tokens changes to 32768.',
      'max_calls_per_candidate':1,'max_output_tokens':32768,'thinking':'enabled','reasoning_effort':'high',
      'primary_results_unchanged':True,'additional_inspections':0,'test_generation':False,'test_execution':False,
      'limits':'A retry plus larger output allowance is not a controlled output-limit-only ablation.',
      'implementation':receipt(__file__),'eligible':eligible})
    print(json.dumps({'eligible':len(eligible),'output':str(OUT)}),flush=True)


def case_run(case,entries):
    # Validation uses the same complete set of source paths and indexed test IDs.
    prepared=read(RUN/'cases'/case/'prepared.json')
    minimal={'source_files':prepared.get('source_files',{}),'source_receipts':prepared['source_receipts'],
             'tests':prepared['tests']}
    del prepared
    results=[]
    for row in entries:
        directory=OUT/'cases'/case/row['candidate']
        done=directory/'result.json'
        if done.exists():
            results.append(read(done));continue
        for expected in (row['primary_result'],row['request']):
            assert receipt(expected['path'])==expected
        payload=read(row['request']['path'])
        request={'id':case+'/'+row['candidate']+':decision_recovery1',
                 'system':payload['messages'][0]['content'],'prompt':payload['messages'][-1]['content'],
                 'max_tokens':32768,'thinking':'enabled','reasoning_effort':'high'}
        transport=directory/'round1'
        if (transport/'manifest.json').exists():
            manifest=read(transport/'manifest.json')
            assert manifest['status'] not in {'dispatching','prepared'},'Ambiguous transport needs review'
        else:
            manifest=dispatch(request,transport,root=ROOT)
        result={'id':case+'/'+row['candidate'],'case':case,'candidate':row['candidate'],
                'primary_decision':'unknown','decision':'unknown','stop_reason':'provider_incomplete',
                'external_model_calls':manifest.get('external_model_calls',0),
                'usage':manifest.get('usage'),'response_model':manifest.get('response_model')}
        if manifest['status']=='complete':
            try:
                action=read(transport/'completion.txt')
                assessment=parse_decision(action,minimal)
                result.update(decision=assessment['decision'],assessment=assessment,stop_reason='model_decided')
            except (ValueError,TypeError,KeyError) as exc:
                result.update(stop_reason='action_error',error=str(exc))
        write_json(done,result)
        results.append(result)
        print(json.dumps({k:result[k] for k in ('case','candidate','decision','stop_reason')},ensure_ascii=False),flush=True)
    return results


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage',choices=['init','run'])
    parser.add_argument('--workers',type=int,default=8)
    args=parser.parse_args()
    if args.stage=='init':initialize();return
    protocol=read(OUT/'protocol.json')
    assert protocol['implementation']==receipt(__file__)
    check_protocol()
    grouped={}
    for row in protocol['eligible']:grouped.setdefault(row['case'],[]).append(row)
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        pending={pool.submit(case_run,c,rows):c for c,rows in grouped.items()}
        for future in as_completed(pending):
            future.result()
    rows=[read(p) for p in sorted(OUT.glob('cases/*/*/result.json'))]
    write_json(OUT/'results.json',rows)
    print(json.dumps({'completed':len(rows),'required':len(protocol['eligible'])}),flush=True)


if __name__=='__main__':main()
