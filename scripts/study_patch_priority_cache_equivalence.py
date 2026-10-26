"""Prepare/freeze a source-only cache-equivalence study; run only when instructed.

Preparation uses standard-library JSON/hash operations only. It does not import
an analyzer, provider, evaluator targets, oracle completions, or runtime logs.
"""
from __future__ import annotations

import argparse
from collections import Counter
import copy
import hashlib
from importlib import metadata
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
VERSION='patch-priority-cache-equivalence-v1'
FROZEN_V1_SEAL='96b1528bd7ff73f5eb645f9e384b43030099a24c45a05c866fcf6dbae5860682'
RUNNER='scripts/study_patch_priority_cache_equivalence.py'
TESTS='tests/test_patch_priority_cache_study.py'
NEW_FILES=[RUNNER,TESTS,'prototypes/patch_observation_priority_v2.py',
    'tests/test_patch_observation_priority_v2.py','tests/test_patch_observation_priority_v2_review.py',
    'prototypes/patch_observation_priority_cached.py','tests/test_patch_observation_priority_cached.py']
ARMS={
    'v1':dict(module='prototypes.patch_observation_priority',kwargs={},cache_equivalence=True),
    'v2_cache':dict(module='prototypes.patch_observation_priority_v2',kwargs={'disable_receiver_fix':True},cache_equivalence=True),
    'v3_cache':dict(module='prototypes.patch_observation_priority_cached',kwargs={'disable_receiver_fix':True},cache_equivalence=True),
    'v2_receiver':dict(module='prototypes.patch_observation_priority_v2',kwargs={'disable_receiver_fix':False},cache_equivalence=False),
}
PRIMARY_ARMS=['v1','v2_cache','v3_cache']
PACKAGES=['tree-sitter','tree-sitter-go','tree-sitter-python','tree-sitter-typescript']


def read(path):return json.loads(Path(path).read_text(encoding='utf-8'))
def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def canonical(value):return json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode()
def value_sha(value):return hashlib.sha256(canonical(value)).hexdigest()
def write(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,sort_keys=True,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')


def sample(case_id,candidates,maximum=5):
    if not 0<maximum<=5:raise ValueError('sample_size_must_be_between_one_and_five')
    if len({c['id'] for c in candidates})!=len(candidates):raise ValueError('duplicate_candidate_ids')
    key=lambda c:(hashlib.sha256((case_id+c['id']).encode('utf-8')).hexdigest(),c['id'])
    return copy.deepcopy(sorted(candidates,key=key)[:maximum])


def arm_order(case_id,receiver=False):
    rotation=int(hashlib.sha256(case_id.encode()).hexdigest(),16)%len(PRIMARY_ARMS)
    order=PRIMARY_ARMS[rotation:]+PRIMARY_ARMS[:rotation]
    return order+(['v2_receiver'] if receiver else [])


def assert_hashes(mapping):
    for name,expected in mapping.items():
        if digest(name)!=expected:raise ValueError('immutable_file_changed:'+name)


def prepare(census,output):
    census=Path(census).resolve();output=Path(output).resolve()
    if output.exists():raise ValueError('prepared_directory_already_exists')
    if digest(census/'seal.json')!=FROZEN_V1_SEAL:raise ValueError('wrong_frozen_v1_census_seal')
    old=read(census/'protocol.json');seal=read(census/'seal.json')
    assert_hashes({str(census/name):sha for name,sha in seal['files_sha256'].items()})
    assert_hashes(old['input_sha256'])
    cases=old['cases'];inventory=Path(old['source_inventory'])
    if len(cases)!=17 or len(set(cases))!=17:raise ValueError('fixed_trial_denominator_changed')
    selections={};references={};inputs={str(census/'protocol.json'):digest(census/'protocol.json'),
        str(census/'seal.json'):digest(census/'seal.json')};candidate_count=0
    # Only original source pools determine selection. Frozen ranks never do.
    for case in cases:
        paths={name:inventory/case/name for name in ['case.json','corpus.json','frontend.json','source_pool.json']}
        for path in paths.values():inputs[str(path.resolve())]=digest(path)
        record=read(paths['case.json']);patch=Path(record['candidate_patch'])
        patch_sha=digest(patch)
        if patch_sha!=record['repository_provenance']['patch_sha256']:
            raise ValueError('submitted_patch_provenance_changed:'+case)
        inputs[str(patch.resolve())]=patch_sha
        pool=read(paths['source_pool.json'])['candidates'];candidate_count+=len(pool)
        selected=sample(case,pool)
        selections[case]=dict(case=case,input_count=len(pool),source_paths={k:str(v.resolve()) for k,v in paths.items()},
            patch_path=str(patch.resolve()),candidate_ids=[c['id'] for c in selected],
            candidates=selected,candidate_sha256={c['id']:value_sha(c) for c in selected},
            sampling_sha256={c['id']:hashlib.sha256((case+c['id']).encode()).hexdigest() for c in selected})
    if candidate_count!=4502:raise ValueError('fixed_source_pool_denominator_changed')
    for case in cases:
        path=census/case/'strict.json';inputs[str(path)]=digest(path)
        wanted=set(selections[case]['candidate_ids'])
        references[case]={r['id']:r['evidence'] for r in read(path)['ranking'] if r['id'] in wanted}
        if set(references[case])!=wanted:raise ValueError('frozen_reference_evidence_missing:'+case)
    output.mkdir(parents=True,exist_ok=False)
    protocol=dict(version=VERSION,phase='selection_prepared_no_algorithm_run',census=str(census),
        source_inventory=str(inventory),cases=cases,input_candidates=4502,
        sample_size_per_trial=5,sample_count=sum(len(r['candidate_ids']) for r in selections.values()),
        sampling='Ascending SHA256((case_id + candidate_id).encode("utf-8")); literal concatenation, candidate_id breaks ties; no filters.',
        candidate_order='Same SHA order for all arms; exact original source candidate dictionaries are retained.',
        arms=ARMS,primary_arms=PRIMARY_ARMS,optional_receiver_arm='v2_receiver; source-support changes only, excluded from cache-equivalence totals',
        arm_order='Rotate primary arms by int(SHA256(case_id),16)%3; optional receiver arm last.',
        isolation='Fresh Python process per trial/arm, PYTHONHASHSEED=0 and bytecode writing disabled.',
        timing=dict(analysis='Includes candidate normalization, Analyzer construction/indexing, and all sampled evidence calls; excludes JSON reads/imports/integrity hashing.',
            worker_total='Parent measures the whole fresh worker, including startup/imports/JSON verification/analysis/output.'),
        equality='Full canonical JSON equality against sealed v1 evidence and between fresh primary arms; object keys sorted, arrays and all values unchanged; no fields stripped. Failed analyses and missing records receive no equality credit.',
        cost='One fresh process per trial/arm, same five candidates in SHA order. Paired trial wall times and total sampled-analysis wall time; no old full-pool timing used as a baseline.',
        scope='Developed 17-trial source corpus, not independent generalization. This sample measures cache equivalence/cost, not selection exposure or defect detection.',
        immutable_inputs_sha256=inputs,frozen_base_code_sha256=old['code_sha256'],additional_code_files=NEW_FILES,
        exclusions=['target labels','oracle/model answers','outcome/runtime logs','hidden verifier','reference patch','exposure scoring'],
        source_inputs_only=True,provider_calls=0,subject_executions=0,
        run_status='not_run; root will separately authorize after source/code freeze')
    write(output/'protocol.json',protocol)
    for case in cases:
        write(output/'selections'/f'{case}.json',selections[case])
        write(output/'references'/f'{case}.json',references[case])
    write(output/'selection_seal.json',dict(files_sha256={str(p.relative_to(output)):digest(p)
        for p in sorted(output.rglob('*')) if p.is_file()}))
    return dict(prepared=str(output),trials=17,source_candidates=4502,sampled_candidates=protocol['sample_count'],algorithm_runs=0)


def verify_selection(prepared):
    prepared=Path(prepared);seal=read(prepared/'selection_seal.json')
    assert_hashes({str(prepared/name):sha for name,sha in seal['files_sha256'].items()})
    protocol=read(prepared/'protocol.json');assert_hashes(protocol['immutable_inputs_sha256'])
    total=0
    for case in protocol['cases']:
        row=read(prepared/'selections'/f'{case}.json')
        pool=read(row['source_paths']['source_pool.json'])['candidates']
        expected=sample(case,pool)
        if canonical(expected)!=canonical(row['candidates']):raise ValueError('sample_or_provenance_changed:'+case)
        total+=len(expected)
    if total!=protocol['sample_count']:raise ValueError('sample_denominator_changed')
    return protocol


def freeze(prepared):
    prepared=Path(prepared).resolve();protocol=verify_selection(prepared)
    if (prepared/'ready.json').exists():raise ValueError('already_frozen')
    files={}
    census=Path(protocol['census'])
    for name,sha in protocol['frozen_base_code_sha256'].items():
        source=census/'code_snapshot'/name
        if digest(source)!=sha:raise ValueError('frozen_base_snapshot_changed:'+name)
        # All shared modules must still match the original frozen source rules.
        if digest(ROOT/name)!=sha:raise ValueError('live_shared_source_differs_from_frozen_v1:'+name)
        files[name]=source
    for name in protocol['additional_code_files']:
        source=ROOT/name
        if not source.is_file():raise ValueError('code_not_ready:'+name)
        files[name]=source
    for name,source in files.items():
        target=prepared/'code_snapshot'/name;target.parent.mkdir(parents=True,exist_ok=True)
        target.write_bytes(source.read_bytes())
    hashes={name:digest(prepared/'code_snapshot'/name) for name in files}
    ready=dict(version=VERSION,selection_seal_sha256=digest(prepared/'selection_seal.json'),
        protocol_sha256=digest(prepared/'protocol.json'),code_sha256=hashes,
        worker_script=str(prepared/'code_snapshot'/RUNNER),python_executable=os.path.abspath(sys.executable),
        environment=dict(python=sys.version,packages={p:metadata.version(p) for p in PACKAGES}),
        algorithm_runs=0,provider_calls=0,subject_executions=0)
    write(prepared/'ready.json',ready)
    return dict(prepared=str(prepared),code_files=len(hashes),sample_count=protocol['sample_count'],ready_sha256=digest(prepared/'ready.json'),algorithm_runs=0)


def verify_ready(prepared):
    prepared=Path(prepared);protocol=verify_selection(prepared);ready=read(prepared/'ready.json')
    if digest(prepared/'selection_seal.json')!=ready['selection_seal_sha256'] or digest(prepared/'protocol.json')!=ready['protocol_sha256']:
        raise ValueError('prepared_protocol_changed')
    assert_hashes({str(prepared/'code_snapshot'/name):sha for name,sha in ready['code_sha256'].items()})
    if sys.version!=ready['environment']['python'] or any(metadata.version(p)!=v for p,v in ready['environment']['packages'].items()):
        raise ValueError('python_or_parser_environment_changed')
    return protocol,ready


def support_counts(records):
    reasons=Counter()
    for value in records.values():
        for unknown in value.get('unknowns',[])+value.get('patch_unknowns',[]):
            reason=unknown if isinstance(unknown,str) else unknown.get('reason','unspecified_source_unknown')
            reasons[reason]+=1
    return dict(evidence_records=len(records),strong=sum(bool(r.get('strong_priority')) for r in records.values()),
        may=sum(bool(r.get('may_priority')) for r in records.values()),
        unknown_candidates=sum(bool(r.get('unknowns') or r.get('patch_unknowns')) for r in records.values()),
        unknown_reason_instances=dict(reasons))


def compare_evidence(reference,records):
    expected=set(reference);actual=set(records)
    equal=[cid for cid in sorted(expected&actual) if canonical(reference[cid])==canonical(records[cid])]
    mismatched=[dict(candidate_id=cid,reference_sha256=value_sha(reference[cid]),observed_sha256=value_sha(records[cid]),
        differing_top_level_fields=sorted(k for k in set(reference[cid])|set(records[cid])
            if (k in reference[cid])!=(k in records[cid]) or canonical(reference[cid].get(k))!=canonical(records[cid].get(k))))
        for cid in sorted(expected&actual) if cid not in equal]
    return dict(expected_records=len(expected),observed_records=len(actual),equal_records=len(equal),
        missing_ids=sorted(expected-actual),unexpected_ids=sorted(actual-expected),mismatched=mismatched,
        exact_all=expected==actual and len(equal)==len(expected))


def aggregate(summaries,expected_counts,arms):
    """Keep every frozen trial/member in denominators, including worker errors."""
    result={}
    for arm in arms:
        rows=[summaries.get(case,{}).get(arm,{}) for case in expected_counts]
        okay=[r for r in rows if r.get('status')=='ok']
        comparisons=[r['reference_equality'] for r in okay if r.get('reference_equality') is not None]
        reasons=Counter()
        for row in okay:reasons.update(row['source_support']['unknown_reason_instances'])
        result[arm]=dict(expected_trials=len(expected_counts),expected_records=sum(expected_counts.values()),
            completed_trials=len(okay),analysis_error_trials=len(rows)-len(okay),
            completed_records=sum(r['source_support']['evidence_records'] for r in okay),
            reference_equality=dict(equal_records=sum(r['equal_records'] for r in comparisons),
                exact_trials=sum(r['exact_all'] for r in comparisons),
                mismatched_records=sum(len(r['mismatched']) for r in comparisons),
                missing_records=sum(len(r['missing_ids']) for r in comparisons)+sum(
                    expected_counts[c] for c in expected_counts if summaries.get(c,{}).get(arm,{}).get('status')!='ok'))
                if ARMS[arm]['cache_equivalence'] else None,
            analysis_wall_seconds=sum(r['analysis_wall_seconds'] for r in okay),
            worker_total_wall_seconds=sum(r.get('worker_total_wall_seconds',0) for r in rows),
            source_support=dict(strong=sum(r['source_support']['strong'] for r in okay),
                may=sum(r['source_support']['may'] for r in okay),
                unknown_candidates=sum(r['source_support']['unknown_candidates'] for r in okay),
                unknown_reason_instances=dict(reasons)))
    return result


def _worker(prepared,case,arm,output):
    # Invoked from the frozen runner in a fresh process by run().
    import importlib
    protocol,ready=verify_ready(prepared)
    if case not in protocol['cases'] or arm not in protocol['arms']:raise ValueError('unknown_trial_or_arm')
    snapshot=Path(prepared)/'code_snapshot';sys.path.insert(0,str(snapshot))
    row=read(Path(prepared)/'selections'/f'{case}.json')
    corpus=read(row['source_paths']['corpus.json']);frontend=read(row['source_paths']['frontend.json'])
    candidates=row['candidates'];patch=Path(row['patch_path']).read_bytes().decode('utf-8')
    before=value_sha([corpus,frontend,candidates,patch])
    settings=protocol['arms'][arm];module=importlib.import_module(settings['module'])
    if Path(module.__file__).resolve()!=snapshot.joinpath(*settings['module'].split('.')).with_suffix('.py').resolve():
        raise ValueError('analysis_module_not_from_frozen_snapshot')
    from relation_search.instrument import _program_edits
    start=time.perf_counter()
    normalized=[dict(c,edits=_program_edits(c)) for c in candidates]
    analyzer=module.Analyzer(corpus,frontend,patch,**settings['kwargs'])
    records={c['id']:analyzer.evidence(c) for c in normalized}
    elapsed=time.perf_counter()-start
    if value_sha([corpus,frontend,candidates,patch])!=before:raise ValueError('analyzer_mutated_source_inputs')
    write(output,dict(case=case,arm=arm,status='ok',analysis_wall_seconds=elapsed,
        candidate_ids=row['candidate_ids'],evidence=records,source_support=support_counts(records),
        work_counts=getattr(analyzer,'work_counts',{}),input_objects_unchanged=True))


def run(prepared,output,receiver=False):
    prepared=Path(prepared).resolve();output=Path(output).resolve();protocol,ready=verify_ready(prepared)
    if output.exists():raise ValueError('run_output_already_exists')
    output.mkdir(parents=True,exist_ok=False)
    plan={case:arm_order(case,receiver) for case in protocol['cases']}
    write(output/'run_protocol.json',dict(version=VERSION,prepared=str(prepared),prepared_ready_sha256=digest(prepared/'ready.json'),
        selection_seal_sha256=digest(prepared/'selection_seal.json'),arm_order=plan,
        optional_receiver_enabled=receiver,source_inputs_only=True,provider_calls=0,subject_executions=0))
    summaries={};pairwise={};expected_counts={}
    environment=dict(os.environ,PYTHONHASHSEED='0',PYTHONDONTWRITEBYTECODE='1')
    for case in protocol['cases']:
        reference=read(prepared/'references'/f'{case}.json');case_results={};arm_evidence={}
        expected_counts[case]=len(reference)
        for arm in plan[case]:
            destination=output/case/(arm+'.json');destination.parent.mkdir(parents=True,exist_ok=True)
            cmd=[ready['python_executable'],'-B',ready['worker_script'],'worker','--prepared',str(prepared),'--case',case,'--arm',arm,'--output',str(destination)]
            start=time.perf_counter()
            completed=subprocess.run(cmd,cwd=str(prepared/'code_snapshot'),env=environment,capture_output=True,text=True)
            duration=time.perf_counter()-start
            (destination.with_suffix('.stdout')).write_text(completed.stdout)
            (destination.with_suffix('.stderr')).write_text(completed.stderr)
            if completed.returncode==0 and destination.is_file():
                result=read(destination)
                arm_evidence[arm]=result['evidence']
                comparison=compare_evidence(reference,result['evidence']) if protocol['arms'][arm]['cache_equivalence'] else None
                case_results[arm]=dict(status='ok',worker_total_wall_seconds=duration,
                    analysis_wall_seconds=result['analysis_wall_seconds'],source_support=result['source_support'],
                    work_counts=result['work_counts'],reference_equality=comparison)
            else:
                case_results[arm]=dict(status='analysis_error',returncode=completed.returncode,
                    worker_total_wall_seconds=duration,expected_records=len(reference),reference_equality=None,
                    reason='worker_failed_no_equality_or_support_credit')
            print(json.dumps(dict(case=case,arm=arm,**case_results[arm])),flush=True)
        summaries[case]=case_results
        pairwise[case]={}
        for first,second in [('v1','v2_cache'),('v1','v3_cache'),('v2_cache','v3_cache')]:
            key=first+'_vs_'+second
            pairwise[case][key]=dict(status='ok',comparison=compare_evidence(arm_evidence[first],arm_evidence[second])) \
                if first in arm_evidence and second in arm_evidence else dict(status='analysis_error',expected_records=len(reference),comparison=None)
    verify_ready(prepared)
    write(output/'summary.json',dict(cases=summaries,trials=len(summaries),sample_count=protocol['sample_count'],
        aggregate=aggregate(summaries,expected_counts,PRIMARY_ARMS+(['v2_receiver'] if receiver else [])),
        pairwise_equality=pairwise,
        interpretation='Source-evidence equality and sampled cold-analysis cost only; no exposure, oracle quality, native or target detection result.',
        provider_calls=0,subject_executions=0))
    write(output/'seal.json',dict(files_sha256={str(p.relative_to(output)):digest(p) for p in sorted(output.rglob('*')) if p.is_file()}))
    return dict(output=str(output),trials=len(summaries),sampled_candidates=protocol['sample_count'])


if __name__=='__main__':
    parser=argparse.ArgumentParser(__doc__);sub=parser.add_subparsers(dest='command',required=True)
    p=sub.add_parser('prepare');p.add_argument('--census',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p=sub.add_parser('freeze');p.add_argument('--prepared',type=Path,required=True)
    p=sub.add_parser('run');p.add_argument('--prepared',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--receiver-arm',action='store_true')
    p=sub.add_parser('worker');p.add_argument('--prepared',type=Path,required=True);p.add_argument('--case',required=True);p.add_argument('--arm',choices=list(ARMS),required=True);p.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if args.command=='prepare':result=prepare(args.census,args.output)
    elif args.command=='freeze':result=freeze(args.prepared)
    elif args.command=='run':result=run(args.prepared,args.output,args.receiver_arm)
    else:_worker(args.prepared,args.case,args.arm,args.output);result={'status':'ok'}
    print(json.dumps(result,sort_keys=True))
