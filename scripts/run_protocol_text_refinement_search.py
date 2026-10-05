"""Reuse the frozen full-test harness for source projection selection and review.

The legacy harness names the first model stage `generation`; this experiment
uses that stage only to select old projection IDs. The program writes all code.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from types import FunctionType

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from relation_search import protocol_text_refinement as relation
from relation_search import protocol_text_refinement_review as review
from relation_search.checkpoint import read
from relational_gap.provider import dispatch
from scripts import run_contract_gap_generation_search as harness
from scripts import run_test_admission as admission
from scripts.run_contract_repair_search import frozen, write

VERSION='controlled-protocol-text-refinement.v1'
one_run=harness.one_run


def _verify_protocol(protocol,phase='semantic_native'):
    if protocol.get('version')!=VERSION or protocol.get('policy')!=relation.POLICY or protocol.get('trial_denominator')!=17:
        raise ValueError('Unsupported source refinement protocol')
    harness._verify_protocol(dict(protocol,version=harness.VERSION),phase)
    if protocol['generation_policy']['max_calls']!=17 or protocol['generation_policy']['max_total_tokens']!=500000 or protocol['generation_policy']['max_output_tokens']!=8192 or protocol['generation_policy']['reasoning_effort']!='low':
        raise ValueError('Projection-selection budget changed')
    if protocol['semantic_policy']['max_calls']!=51 or protocol['semantic_policy']['max_total_tokens']!=1500000 or protocol['max_native_executions']!=68:
        raise ValueError('Full-test review/native budget changed')


def _engine():
    namespace=dict(vars(harness))
    overrides=dict(__name__=__name__,__file__=__file__,VERSION=VERSION,relation=relation,review=review,
        dispatch=dispatch,one_run=one_run,_verify_protocol=_verify_protocol)
    namespace.update(overrides)
    for name,function in vars(harness).items():
        if name not in overrides and isinstance(function,FunctionType) and function.__module__==harness.__name__:
            copied=FunctionType(function.__code__,namespace,name,function.__defaults__,function.__closure__)
            copied.__kwdefaults__=function.__kwdefaults__;namespace[name]=copied
    return namespace


def prepare(args):
    source=args.source_cohort.resolve()
    if read(source/'seal.json')!=frozen(source/'prepared.json'):
        raise ValueError('Original preparation seal differs')
    previous=read(source/'prepared.json')
    harness._verify_protocol(previous,'generation')
    harness._verify_nested_receipts(previous['algorithm'])
    harness._verify_nested_receipts(previous['algorithm_entrypoints'])
    if len(previous['cases'])!=17 or previous['algorithm_entrypoints']['driver']!=frozen(harness.__file__):
        raise ValueError('Complete frozen R18 source preparation required')
    deadline=admission._deadline(args.deadline_utc)
    if deadline is None:raise ValueError('Deadline required')
    args.output.mkdir(parents=True,exist_ok=False)
    cases=[]
    for old in previous['cases']:
        harness._verify_case_inputs(old)
        corpus,frontend=harness._context(old)
        prepared=relation.prepare(corpus,frontend,(Path(old['source'])/'issue.md').read_text())
        directory=args.output/'cases'/old['case']/'generation'
        write(directory/'preparation.json',prepared)
        if prepared['request']:write(directory/'request.json',prepared['request'])
        cases.append(dict(old,generation=frozen(directory/'preparation.json'),
            generation_request=frozen(directory/'request.json') if prepared['request'] else None,
            candidates=[],status=prepared['status']))
        print(json.dumps(dict(case=old['case'],hosts=prepared['hosts'],slots=len(prepared['slots']),
            prompt_bytes=prepared['request']['prompt_bytes'] if prepared['request'] else 0,
            omissions=len(prepared['host_omissions']),indexed_original_tests=prepared['indexed_original_tests'])),flush=True)
    admission._preload_local_imports(sys.modules[__name__])
    engine=_engine()
    record=dict(previous,version=VERSION,policy=relation.POLICY,cases=cases,
        source_cohort=frozen(source/'prepared.json'),algorithm=admission._loaded_sources(),
        algorithm_entrypoints=engine['_entrypoints'](),deadline_utc=deadline.isoformat(),
        generation_policy=dict(previous['generation_policy'],max_total_tokens=500000,max_output_tokens=8192,reasoning_effort='low',
            purpose='projection_ID_selection_only_no_model_code_generation'),
        source_cohort_use='Only original repository snapshots, exact fixed corpus test IDs and source receipts. No generated outputs, reviews or outcomes.',
        comparative_limits=['Controlled extension of existing protocol projection transport; development-selected text cardinality/class transforms.',
            'Exactly the existing3029 source test IDs across17 trials; no recovery of unindexed test definitions.',
            'Old CSI guard remains unchanged. Keyword-unknown association can enter a hypothesis only with resolved fixture/import/class/consumer source; fresh explicit domain and reentry checks are mandatory.',
            'Complete original test prefix stays unchanged. Only selected old predicate projections are appended. No new output constant or oracle code from the model.',
            'Legacy generation stage/cost field names mean projection selection in this experiment. It is not a direct generation or pure payload ablation.'],
        created_utc=datetime.now(timezone.utc).isoformat(),provider_calls=0,native_executions=0)
    _verify_protocol(record,'generation');engine['_verify_algorithm'](record)
    write(args.output/'prepared.json',record);write(args.output/'seal.json',frozen(args.output/'prepared.json'))
    return dict(prepared=frozen(args.output/'prepared.json'),trials=17,requests=sum(bool(c['generation_request']) for c in cases),
        slots=sum(len(read(c['generation']['path'])['slots']) for c in cases),provider_calls=0,native_executions=0)


def select(args):return _engine()['generate'](args)
def review_all(args):return _engine()['review_all'](args)
def run(args):return _engine()['run'](args)


if __name__=='__main__':
    parser=argparse.ArgumentParser(__doc__)
    parser.add_argument('stage',choices=['prepare','select','review','run'])
    parser.add_argument('--source-cohort',type=Path);parser.add_argument('--input',type=Path)
    parser.add_argument('--output',type=Path);parser.add_argument('--deadline-utc')
    args=parser.parse_args()
    if args.stage=='prepare' and not all((args.source_cohort,args.output,args.deadline_utc)):parser.error('prepare requires source-cohort, output and deadline-utc')
    if args.stage!='prepare' and args.input is None:parser.error('--input required')
    result={'prepare':prepare,'select':select,'review':review_all,'run':run}[args.stage](args)
    print(json.dumps({k:v for k,v in result.items() if k!='results'}))
