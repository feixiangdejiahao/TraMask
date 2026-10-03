"""Execute all frozen first-rank oracle-interface proposals without new calls.

This diagnostic revalidates saved responses with the current guarded codecs.
It includes the original raw/disabled arm, retains absent proposals, and never
selects candidates from evaluation labels or native outcomes. No detector gate
is inferred from a derivation response or a controlled native failure.
"""
from __future__ import annotations

import argparse
from datetime import datetime,timezone
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from relation_search import expected_slots,literal_value_slots
from relation_search.candidate_edit_transport import rewrite_view,verify_emission,GO_MATERIALIZER_SOURCE
from relation_search.checkpoint import read
from scripts import run_test_admission as admission
from scripts.run_contract_repair_search import execute,write,frozen,verify
from scripts.run_type_projection_component import emit


VERSION='all-first-rank-oracle-proposals-native-component.v1'


def prepare(args):
    root=args.output;root.mkdir(parents=True,exist_ok=False)
    verify(read(args.source/'seal.json'));prior=read(args.source/'prepared.json')
    verify(prior['source']);first_rank=read(prior['source']['path'])
    source_cases={row['case']:row for row in first_rank['cases']}
    queue=[];baselines=set()
    for item in prior['items']:
        if item['case'] not in baselines:
            queue.append(dict(case=item['case'],arm='raw_disabled',request=item['raw_request'],corpus=item['corpus']))
            baselines.add(item['case'])
        queue.append(dict(case=item['case'],arm=item['arm'],request=item['request'],corpus=item['corpus']))
    items=[];corpora={}
    for index,item in enumerate(queue):
        verify(item['request']);verify(item['corpus']);request=read(item['request']['path'])
        directory=Path(item['request']['path']).parent;completion=directory/'completion'
        receipt=read(completion/'manifest.json')
        if receipt.get('request_id')!=request['id']:raise ValueError('Completion/request identity mismatch')
        cp=item['corpus']['path']
        if cp not in corpora:corpora[cp]=read(cp)
        method=literal_value_slots if item['arm'].startswith('values') else expected_slots
        if receipt['status']=='complete':
            decision=method.validate(request,(completion/'completion.txt').read_text(),corpora[cp],finish_reason=receipt.get('finish_reason'))
        else:decision=dict(status='unknown',candidate=None,reason='provider_not_complete')
        candidate=decision.pop('candidate');name=f'item_{index:04d}';target=root/'cases'/name
        write(target/'decision.json',decision);program=None
        if candidate is not None:
            candidate=rewrite_view(candidate);write(target/'program.json',candidate);program=frozen(target/'program.json')
        inputs=source_cases[item['case']]['source_inputs']
        for record in inputs.values():verify(record)
        items.append(dict(name=name,case=item['case'],arm=item['arm'],request=item['request'],decision=decision,
            response=frozen(completion/'completion.txt') if (completion/'completion.txt').exists() else None,
            provider_receipt=frozen(completion/'manifest.json'),program=program,source_inputs=inputs,
            source=str(Path(inputs['corpus.json']['path']).parent),prior_tokens=(receipt.get('usage') or {}).get('total_tokens')))
    for module in (expected_slots,literal_value_slots):admission._preload_local_imports(module)
    protocol=dict(version=VERSION,items=items,excluded=prior['excluded'],
        trial_denominator=len(first_rank['cases']),source=frozen(args.source/'prepared.json'),
        algorithm=admission._loaded_sources(),go_binding_materializer=frozen(GO_MATERIALIZER_SOURCE),
        timeout=180,deadline_utc=args.deadline_utc,max_native_executions=64,
        ordering='source_case_then_raw_disabled_raw_enabled_values_disabled_values_enabled',
        selection='Every derived full program from the fixed first-rank cohort; no runtime-dependent stopping.',
        codec_policy='Raw v1; structured v2 permits only byte-identical echoed source_reference metadata.',
        native_outcomes_for_oracle_derivation=False,evaluation_labels_used=False,
        external_model_calls=0,reported_alerts=0,created_utc=datetime.now(timezone.utc).isoformat())
    write(root/'prepared.json',protocol);write(root/'seal.json',frozen(root/'prepared.json'))
    return dict(items=len(items),proposals=sum(bool(i['program']) for i in items),excluded=prior['excluded'],prepared=frozen(root/'prepared.json'))


def run(args):
    root=args.input;verify(read(root/'seal.json'));p=read(root/'prepared.json')
    admission.verify_seal(p['algorithm']);verify(p['go_binding_materializer'])
    deadline=datetime.fromisoformat(p['deadline_utc'].replace('Z','+00:00'));count=0;results=[]
    for item in p['items']:
        directory=root/'cases'/item['name']
        if (directory/'outcome.json').exists():outcome=read(directory/'outcome.json')
        else:
            outcome=dict(name=item['name'],case=item['case'],arm=item['arm'],program=item['program'],
                derivation_status=item['decision']['status'],native=None,transport=None,semantic_validity='unconfirmed',detector_alert=False)
            if item['program']:
                if count>=p['max_native_executions'] or (deadline-datetime.now(timezone.utc)).total_seconds()<p['timeout']+30:
                    outcome['status']='execution_budget'
                else:
                    for receipt in (item['program'],*item['source_inputs'].values()):verify(receipt)
                    candidate=read(item['program']['path']);corpus=read(item['source_inputs']['corpus.json']['path'])
                    artifact=directory/'native/emitted/group_000'
                    if not (artifact/'manifest.json').exists():artifact=emit(candidate,Path(item['source']),directory/'native',p)
                    transport=verify_emission(corpus,candidate,artifact);write(directory/'transport.json',transport)
                    outcome['transport']=transport
                    if transport['status']=='matched':
                        outcome['native']=execute(candidate,Path(item['source']),corpus,directory/'native',p)
                        outcome['status']='executed'
                    else:outcome['status']='program_transport_mismatch'
            else:outcome['status']='no_derived_program'
            write(directory/'outcome.json',outcome)
        count+=int(outcome['native'] is not None);results.append(outcome)
        print(json.dumps(dict(name=item['name'],case=item['case'],arm=item['arm'],status=outcome['status'],
            controlled_failure=bool(outcome['native'] and outcome['native']['controlled_failure']),native_executions=count)),flush=True)
    admission.verify_seal(p['algorithm'])
    summary=dict(version=VERSION,items=results,excluded=p['excluded'],trial_denominator=p['trial_denominator'],
        external_model_calls=0,native_executions=count,detector_alerts=0,completed_utc=datetime.now(timezone.utc).isoformat())
    write(root/'summary.json',summary)
    return dict(items=len(results),native_executions=count,detector_alerts=0)


if __name__=='__main__':
    parser=argparse.ArgumentParser(__doc__);parser.add_argument('stage',choices=['prepare','run'])
    parser.add_argument('--source',type=Path);parser.add_argument('--input',type=Path);parser.add_argument('--output',type=Path)
    parser.add_argument('--deadline-utc',default='2026-10-03T20:00:00Z')
    args=parser.parse_args();print(json.dumps(prepare(args) if args.stage=='prepare' else run(args)))
