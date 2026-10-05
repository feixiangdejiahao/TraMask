"""Independent requests for the original complete-context budget omissions.

Source rebuilding is local. Fixed slots reuse the atomic raw/semantic/native
harness through private function globals, without modifying sealed modules.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from types import FunctionType

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from relation_search import omitted_anchor_proposals as relation
from scripts import run_atomic_contract_gap_generation_search as original
from relational_gap.provider import dispatch

VERSION='controlled-omitted-anchor-generation.v1'
GENERATION_POLICY=dict(original.GENERATION_POLICY,max_calls=12,reasoning_effort='low')
SEMANTIC_POLICY=dict(original.SEMANTIC_POLICY,max_calls=12,max_total_tokens=1000000)


def _verify_case_inputs(case):
    harness._verify_case_inputs(case)
    for key in ('inherited_generation_preparation','inherited_generation_request','recovered_source_preparation','recovery_source_projection'):
        if case.get(key):verify(case[key])
    inherited=read(case['inherited_generation_preparation']['path'])
    recovered=read(case['recovered_source_preparation']['path'])
    manifest=read(case['recovery_source_projection']['path'])
    if manifest['original_inputs']!={key:case['inputs'][key] for key in ('corpus.json','frontend.json')}:
        raise ValueError('Recovery source projection origin differs')
    harness._verify_nested_receipts(manifest)
    corpus=read(manifest['corpus']['path'])
    relation.validate_recovery(corpus,inherited,recovered)
    for slot in case['slots']:
        verify(slot['preparation'])
        expected=relation.prepare_slot(recovered,slot['slot'])
        if read(slot['preparation']['path'])!=expected or slot['status']!=expected['status'] or slot['seed_alias']!=expected.get('inherited_seed_alias'):
            raise ValueError('Recovered slot differs from fixed original omitted anchor')
        if slot['request']:
            verify(slot['request'])
            if read(slot['request']['path'])!=expected['request']:
                raise ValueError('Recovered slot request differs')
        elif expected['request'] is not None:
            raise ValueError('Recovered slot request omitted')

def _prepare(args):
    source_root = args.source_cohort.resolve()
    if read(source_root/'seal.json') != frozen(source_root/'prepared.json'):
        raise ValueError('R18 source preparation seal differs')
    previous = read(source_root/'prepared.json')
    harness._verify_protocol(previous, 'generation')
    # Recovery loads new modules absent from R18's process closure.
    # Verify the inherited bytes, then seal the actually executed new closure.
    harness._verify_nested_receipts(previous['algorithm'])
    harness._verify_nested_receipts(previous['algorithm_entrypoints'])
    if (previous['algorithm_entrypoints']['driver'] != frozen(harness.__file__)
            or previous['algorithm_entrypoints']['constructor'] != frozen(relation.core.__file__)):
        raise ValueError('R18 inherited decoder or driver differs')
    if len(previous['cases']) != EXPECTED_TRIALS:
        raise ValueError('Complete seventeen-trial R18 source preparation required')
    deadline = admission._deadline(args.deadline_utc)
    if deadline is None:
        raise ValueError('Deadline required')
    args.output.mkdir(parents=True, exist_ok=False)
    cases = []
    for old in previous['cases']:
        harness._verify_case_inputs(old)
        prepared = read(old['generation']['path'])
        if old['generation_request'] and read(old['generation_request']['path']) != prepared['request']:
            raise ValueError('Inherited source request differs from preparation')
        corpus, frontend = harness._context(old)
        recovered = relation.recover(corpus, frontend, (Path(old['source'])/'issue.md').read_text(), prepared)
        slots = []
        directory = args.output/'cases'/old['case']/'generation'
        write(directory/'recovered_source_preparation.json', recovered)
        for rank in (1, 2, 3):
            result = relation.prepare_slot(recovered, rank)
            target = directory/f'slot_{rank:04d}'
            write(target/'preparation.json', result)
            if result['request'] is not None: write(target/'request.json', result['request'])
            slots.append(dict(slot=rank, preparation=frozen(target/'preparation.json'),
                request=frozen(target/'request.json') if result['request'] is not None else None,
                status=result['status'], seed_alias=result.get('inherited_seed_alias')))
        write(directory/'preparation.json', dict(version=relation.VERSION, policy=relation.POLICY,
            inherited_preparation=old['generation'], inherited_request=old['generation_request'], slots=slots))
        cases.append(dict(old, generation=frozen(directory/'preparation.json'), generation_request=None,
            inherited_generation_preparation=old['generation'],
            inherited_generation_request=old['generation_request'],
            recovered_source_preparation=frozen(directory/'recovered_source_preparation.json'),
            recovery_source_projection=old['review_projection'], slots=slots,
            candidates=[], status='atomic_slots_prepared'))
    admission._preload_local_imports(sys.modules[__name__])
    engine = _engine()
    protocol = dict(previous, version=VERSION, phase='generation', policy=relation.POLICY,
        algorithm=admission._loaded_sources(), algorithm_entrypoints=engine['_entrypoints'](),
        cases=cases, source_cohort=frozen(source_root/'prepared.json'),
        source_cohort_use='Only original R18 source preparation, fixed whole-context omission ledger and original source projections. Rebuild omitted anchors independently; never generation results, reviews or outcomes.',
        reused_harness=frozen(harness.__file__), reused_decoder=frozen(relation.core.__file__),
        deadline_utc=deadline.isoformat(), generation_policy=GENERATION_POLICY,
        semantic_policy=SEMANTIC_POLICY, max_native_executions=4*len(cases),
        comparative_limits=['Independent generation requests recover all twelve original R18 whole_context_prompt_budget omissions, in original omission order.',
            'All17 trials and all three slot ledger positions remain; missing/unknown/duplicate slots are never refilled.',
            'Context granularity, independent request budget and generation reasoning effort change together. This is not a pure reasoning or retrieval ablation.',
            'Original issue/API catalog and full single-anchor P/Q/source bundles remain; no oracle-dependency retrieval is added.',
            'Attach exact source provenance before fresh complete-test review. Original controls and first-failure confirmation remain required.',
            'The 1M cap does not guarantee all12 calls; actual/reserved usage and the deadline govern stopping.'],
        created_utc=datetime.now(timezone.utc).isoformat())
    _verify_protocol(protocol, 'generation'); engine['_verify_algorithm'](protocol)
    write(args.output/'prepared.json', protocol); write(args.output/'seal.json', frozen(args.output/'prepared.json'))
    return dict(trials=len(cases), slots=3*len(cases), requests=sum(bool(s['request']) for c in cases for s in c['slots']),
        prepared=frozen(args.output/'prepared.json'), provider_calls=0, native_executions=0)



def engine():
    namespace=dict(vars(original),__name__=__name__,__file__=__file__,VERSION=VERSION,
        relation=relation,dispatch=dispatch,GENERATION_POLICY=GENERATION_POLICY,SEMANTIC_POLICY=SEMANTIC_POLICY)
    for name,function in vars(original).items():
        if isinstance(function,FunctionType) and function.__module__==original.__name__ and name not in {'prepare','_verify_case_inputs'}:
            copied=FunctionType(function.__code__,namespace,name,function.__defaults__,function.__closure__)
            copied.__kwdefaults__=function.__kwdefaults__;namespace[name]=copied
    for name,function in [('prepare',_prepare),('_verify_case_inputs',_verify_case_inputs)]:
        namespace[name]=FunctionType(function.__code__,namespace,name,function.__defaults__,function.__closure__)
    return namespace


if __name__=='__main__':
    parser=argparse.ArgumentParser(__doc__)
    parser.add_argument('stage',choices=['prepare','generate','review','run'])
    parser.add_argument('--source-cohort',type=Path);parser.add_argument('--output',type=Path)
    parser.add_argument('--input',type=Path);parser.add_argument('--deadline-utc')
    args=parser.parse_args()
    if args.stage=='prepare' and not all((args.source_cohort,args.output,args.deadline_utc)):
        parser.error('prepare requires --source-cohort, --output and --deadline-utc')
    if args.stage!='prepare' and args.input is None:parser.error('--input required')
    result=engine()[{'review':'review_all'}.get(args.stage,args.stage)](args)
    print(json.dumps({k:v for k,v in result.items() if k!='results'}))
