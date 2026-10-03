"""Offline bounded prefix construction on an explicit calibration cohort.

Every supplied program participates. Each prefix retains all input edits. Run
prefixes in increasing source order, round-robin across programs. Stop a program
at its first controlled failure or a failed/unavailable source control. This
component reports probes, not detector alerts, and never calls a model.
"""
from __future__ import annotations

import argparse
from datetime import datetime,timezone
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from relation_search import oracle,test_prefix_projection,prefix_finalization
from relation_search.candidate_edit_transport import rewrite_view,verify_emission,GO_MATERIALIZER_SOURCE
from relation_search.checkpoint import read
from scripts import run_test_admission as admission
from scripts.run_contract_repair_search import execute,write,frozen,verify
from scripts.run_type_projection_component import emit


VERSION='finite-source-prefix-construction-component.v5'


def prepare(args):
    root=args.output;root.mkdir(parents=True,exist_ok=False);cohort=read(args.cohort);items=[];cache={}
    for index,item in enumerate(cohort['items']):
        name=f'item_{index:04d}'
        inputs={name:row for name,row in item['source_inputs'].items() if name in {'corpus','frontend','candidates'}}
        for receipt in inputs.values():verify(receipt)
        for role,receipt in inputs.items():
            if receipt['path'] not in cache:cache[receipt['path']]=read(receipt['path'])
        corpus=cache[inputs['corpus']['path']];frontend=cache[inputs['frontend']['path']]
        catalog=cache[inputs['candidates']['path']]
        if isinstance(catalog,dict):catalog=catalog['candidates']
        candidate=next(row for row in catalog if row['id']==item['candidate_id'])
        constructor=prefix_finalization if args.retain_source_finalizers else test_prefix_projection
        projection=constructor.construct(corpus,frontend,candidate,limit=args.max_prefixes)
        prefixes=projection.pop('candidates');programs=prefixes+[rewrite_view(candidate)]
        directory=root/'cases'/name;write(directory/'construction.json',projection)
        rows=[]
        for rank,program in enumerate(programs,1):
            p=directory/f'candidate_{rank:04d}'/'program.json';write(p,program)
            rows.append(dict(rank=rank,candidate_id=program['id'],is_original=rank==len(programs),program=frozen(p)))
        items.append(dict(name=name,source_cohort_name=item['name'],case=item['case'],parent=item['candidate_id'],source_inputs=inputs,
            source=str(Path(inputs['corpus']['path']).parent),programs=rows))
    unchanged=[];paired_source=None;cohort_parents=len(items)
    if args.changed_from:
        verify(read(args.changed_from/'seal.json'));old=read(args.changed_from/'prepared.json')
        if old['cohort']!=frozen(args.cohort):raise ValueError('Paired construction cohort differs')
        def identity(item):return json.dumps([item['parent'],item['source_inputs']],sort_keys=True)
        previous={identity(item):item for item in old['items']}
        if len(previous)!=len(old['items']):raise ValueError('Ambiguous paired parent identity')
        changed=[]
        for item in items:
            prior=previous.get(identity(item))
            if prior is not None:
                for program in prior['programs']:verify(program['program'])
            same=prior is not None and [r['program']['sha256'] for r in item['programs']]==[r['program']['sha256'] for r in prior['programs']]
            (unchanged if same else changed).append(item)
        items=changed;paired_source=frozen(args.changed_from/'prepared.json')
    admission._preload_local_imports(test_prefix_projection)
    protocol=dict(version=VERSION,items=items,algorithm=admission._loaded_sources(),cohort=frozen(args.cohort),
        max_prefixes=args.max_prefixes,max_native_executions=args.max_native_executions,timeout=180,
        retain_source_finalizers=args.retain_source_finalizers,
        cohort_parents=cohort_parents,unchanged_source_program_parents=unchanged,paired_source=paired_source,
        deadline_utc=args.deadline_utc,ordering='prefix_rank_then_cohort_order',
        stop='first_controlled_failure_or_failed_source_control_per_program',
        original_program_fallback=True,exact_emitted_test_ast_required=True,external_model_calls=0,detector_alerts=0,
        go_binding_materializer=frozen(GO_MATERIALIZER_SOURCE),
        evaluation_labels_used=False,prior_native_results_used=False,
        created_utc=datetime.now(timezone.utc).isoformat())
    write(root/'prepared.json',protocol);write(root/'seal.json',frozen(root/'prepared.json'))
    return dict(parents=len(items),cohort_parents=cohort_parents,unchanged=len(unchanged),programs=sum(len(i['programs']) for i in items),prepared=frozen(root/'prepared.json'))


def run(args):
    root=args.input;verify(read(root/'seal.json'));p=read(root/'prepared.json')
    verify(p['go_binding_materializer'])
    admission.verify_seal(p['algorithm']);results={i['name']:dict(name=i['name'],case=i['case'],parent=i['parent'],attempts=[],first_failure=None,stop_reason=None) for i in p['items']}
    count=0;deadline=datetime.fromisoformat(p['deadline_utc'].replace('Z','+00:00'))
    for rank in range(max((len(i['programs']) for i in p['items']),default=0)):
        for item in p['items']:
            result=results[item['name']]
            if result['stop_reason'] or rank>=len(item['programs']):continue
            entry=item['programs'][rank];directory=root/'cases'/item['name']/f'candidate_{rank+1:04d}'
            if (directory/'outcome.json').exists():outcome=read(directory/'outcome.json')
            else:
                if count>=p['max_native_executions'] or (deadline-datetime.now(timezone.utc)).total_seconds()<p['timeout']+30:
                    result['stop_reason']='execution_budget';continue
                for receipt in item['source_inputs'].values():verify(receipt)
                verify(entry['program']);candidate=read(entry['program']['path']);corpus=read(item['source_inputs']['corpus']['path'])
                if not (directory/'native/emitted/group_000/manifest.json').exists():
                    artifact=emit(candidate,Path(item['source']),directory/'native',p)
                else:artifact=directory/'native/emitted/group_000'
                transport=verify_emission(corpus,candidate,artifact);write(directory/'transport.json',transport)
                native=(execute(candidate,Path(item['source']),corpus,directory/'native',p)
                        if transport['status']=='matched' else None)
                outcome=dict(rank=rank+1,is_original=entry['is_original'],program=entry['program'],native=native,transport=transport,
                             semantic_validity='unconfirmed',detector_alert=False)
                write(directory/'outcome.json',outcome)
            result['attempts'].append(outcome)
            if outcome['native'] is None:
                result['stop_reason']='program_transport_mismatch'
                print(json.dumps(dict(case=item['case'],parent=item['name'],rank=rank+1,transport=outcome['transport'])),flush=True)
                continue
            count+=1
            if outcome['native']['controlled_failure']:
                result['first_failure']=outcome;result['stop_reason']='first_controlled_failure'
            elif outcome['native']['controls']['status']!='all_source_controls_passed':result['stop_reason']='source_control_unavailable_or_failed'
            print(json.dumps(dict(case=item['case'],parent=item['name'],rank=rank+1,controlled_failure=outcome['native']['controlled_failure'],native_executions=count)),flush=True)
    admission.verify_seal(p['algorithm'])
    for result in results.values():write(root/'cases'/result['name']/'result.json',result)
    summary=dict(version=VERSION,results=list(results.values()),external_model_calls=0,native_executions=count,
        cohort_parents=p.get('cohort_parents',len(p['items'])),unchanged_source_program_parents=len(p.get('unchanged_source_program_parents',[])),
        detector_alerts=0,completed_utc=datetime.now(timezone.utc).isoformat())
    write(root/'summary.json',summary)
    return dict(parents=len(results),native_executions=count,controlled_failures=sum(bool(r['first_failure']) for r in results.values()),detector_alerts=0)


if __name__=='__main__':
    parser=argparse.ArgumentParser(__doc__);parser.add_argument('stage',choices=['prepare','run'])
    parser.add_argument('--cohort',type=Path);parser.add_argument('--output',type=Path);parser.add_argument('--input',type=Path)
    parser.add_argument('--max-prefixes',type=int,default=16);parser.add_argument('--max-native-executions',type=int,default=256)
    parser.add_argument('--retain-source-finalizers',action='store_true')
    parser.add_argument('--changed-from',type=Path)
    parser.add_argument('--deadline-utc',default='2026-10-03T19:00:00Z');a=parser.parse_args()
    print(json.dumps(prepare(a) if a.stage=='prepare' else run(a)))
