"""Prospective source-repair ablations on the previously sealed 85 samples.

Prepare and freeze perform JSON/hash operations only. The run command needs
separate authorization; it never invokes a provider or executes a subject.
"""
from __future__ import annotations

import argparse
from collections import Counter
import importlib
from importlib import metadata
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts import study_patch_priority_cache_equivalence as cache

VERSION='source-repair-prospective-v1'
RUNNER='scripts/study_source_repairs.py'
TESTS='tests/test_source_repairs_study.py'
CACHE_READY_SHA='a51eadb2c980bd7686387077a830996ff57aedd7e5d4355244d41472d3e9659e'
CACHE_RUN_SEAL_SHA='2034ee5ab3e1883dac7f283297834c80c61b46c7ccf37d99c72742fa4dc843fc'
NEW_FILES=[RUNNER,TESTS,'prototypes/repaired_observation_analysis.py',
    'prototypes/observation_correspondence.py','prototypes/source_argument_binding.py',
    'prototypes/source_receiver_binding.py','tests/test_repaired_observation_analysis.py',
    'tests/test_observation_correspondence.py','tests/test_source_argument_binding.py',
    'tests/test_source_receiver_binding.py']
ARMS={
    'cached_baseline':dict(module='prototypes.patch_observation_priority_cached',
        kwargs=dict(disable_receiver_fix=True)),
    'repaired_control':dict(module='prototypes.repaired_observation_analysis',
        kwargs=dict(repair_correspondence=False,repair_arguments=False,disable_receiver_fix=True)),
    'correspondence_only':dict(module='prototypes.repaired_observation_analysis',
        kwargs=dict(repair_correspondence=True,repair_arguments=False,disable_receiver_fix=True)),
    'binder_receiver_only':dict(module='prototypes.repaired_observation_analysis',
        kwargs=dict(repair_correspondence=False,repair_arguments=True,disable_receiver_fix=False)),
    'both':dict(module='prototypes.repaired_observation_analysis',
        kwargs=dict(repair_correspondence=True,repair_arguments=True,disable_receiver_fix=False)),
}
ARM_NAMES=list(ARMS)


def order(case):
    offset=int(cache.hashlib.sha256(case.encode()).hexdigest(),16)%len(ARM_NAMES)
    return ARM_NAMES[offset:]+ARM_NAMES[:offset]


def base_fields(records):
    """Supplemental comparison; full evidence and repair facts stay preserved."""
    return {cid:{key:value for key,value in row.items() if key!='source_repairs'} for cid,row in records.items()}


def source_counts(records):
    counts=cache.support_counts(records);statuses=Counter();bases=Counter();unknowns=Counter()
    for row in records.values():
        for observation in row.get('source_repairs',{}).get('observations',[]):
            statuses[observation.get('status','unspecified')]+=1
            if observation.get('basis'):bases[observation['basis']]+=1
            if observation.get('reason'):unknowns[observation['reason']]+=1
    counts['correspondence_observation_instances']=dict(statuses)
    counts['correspondence_basis_instances']=dict(bases)
    counts['correspondence_unknown_reason_instances']=dict(unknowns)
    return counts


def prepare(cache_prepared,cache_run,output,worker_seconds=120,total_seconds=1200):
    cache_prepared=Path(cache_prepared).resolve();cache_run=Path(cache_run).resolve();output=Path(output).resolve()
    if output.exists():raise ValueError('prepared_directory_already_exists')
    if not 0<worker_seconds<=120 or not worker_seconds<=total_seconds<=1200:
        raise ValueError('cost_bounds_outside_predeclared_maximum')
    if cache.digest(cache_prepared/'ready.json')!=CACHE_READY_SHA:raise ValueError('wrong_sealed_cache_preparation')
    if cache.digest(cache_run/'seal.json')!=CACHE_RUN_SEAL_SHA:raise ValueError('wrong_completed_cache_run')
    old,ready=cache.verify_ready(cache_prepared)
    cache.assert_hashes({str(cache_run/name):sha for name,sha in cache.read(cache_run/'seal.json')['files_sha256'].items()})
    if len(old['cases'])!=17 or old['sample_count']!=85 or old['input_candidates']!=4502:
        raise ValueError('fixed_source_denominator_changed')
    selections={};references={};input_hashes=dict(old['immutable_inputs_sha256'])
    for path in [cache_prepared/'ready.json',cache_prepared/'selection_seal.json',cache_prepared/'protocol.json',cache_run/'seal.json']:
        input_hashes[str(path)]=cache.digest(path)
    for case in old['cases']:
        selected=cache.read(cache_prepared/'selections'/f'{case}.json')
        reference=cache.read(cache_prepared/'references'/f'{case}.json')
        cached_path=cache_run/case/'v3_cache.json';cached=cache.read(cached_path)
        input_hashes[str(cached_path)]=cache.digest(cached_path)
        if len(selected['candidate_ids'])!=5 or selected['candidate_ids']!=[c['id'] for c in selected['candidates']]:
            raise ValueError('sample_order_changed:'+case)
        if cached['status']!='ok' or not cache.compare_evidence(reference,cached['evidence'])['exact_all']:
            raise ValueError('cache_reference_not_exact:'+case)
        if set(reference)!=set(selected['candidate_ids']):raise ValueError('reference_members_changed:'+case)
        selections[case]=selected
        references[case]=dict(frozen_v1=reference,sealed_cached=cached['evidence'])
    output.mkdir(parents=True,exist_ok=False)
    protocol=dict(version=VERSION,phase='prepared_no_algorithm_run',cases=old['cases'],sample_count=85,
        input_candidates=4502,cache_prepared=str(cache_prepared),cache_run=str(cache_run),
        selection='Exact previous sealed 17 x 5 candidate dictionaries and SHA order; no re-selection or filtering.',
        arms=ARMS,arm_order='Rotate five arms by int(SHA256(case_id),16)%5; same case order as previous sealed study.',
        cost=dict(per_worker_wall_seconds=worker_seconds,total_run_wall_seconds=total_seconds,
            attempts=85,retries=0,replacement_samples=0,
            failure='Timeout, worker error, and budget-not-started keep all 17 trials/85 members in each arm denominator; no support/equality credit.'),
        comparisons=dict(complete_json='Canonical full JSON; no field stripped, arrays unchanged.',
            base_fields='Supplemental exact comparison excluding only the newly added top-level source_repairs field; full repair observations are counted separately and preserved.',
            controls='Fresh cached baseline vs frozen v1; repaired_control common fields vs sealed cached baseline. Controls are checked, never assumed.',
            ablations='Each repair arm vs repaired_control; both vs each single repair. Differences are source facts, not correct oracles.'),
        timing=dict(analysis='Candidate normalization + Analyzer construction/indexing + five evidence calls.',
            worker='Fresh process startup/import/JSON/integrity checks + analysis/output; bounded by wall deadline.'),
        source_support='Strong/may flags, unknown candidate counts, repeated reason and correspondence observation instances. These are bounded analyzer claims, not oracle/dispatch/path correctness.',
        scope='Previously developed 17 trials, not independent generalization; no exposure or detection score.',
        immutable_inputs_sha256=input_hashes,frozen_cache_code_sha256=ready['code_sha256'],additional_code_files=NEW_FILES,
        forbidden=['target labels','oracle/model answers','native/runtime outcomes','hidden verifier','reference patch'],
        source_inputs_only=True,provider_calls=0,subject_executions=0,algorithm_runs=0)
    cache.write(output/'protocol.json',protocol)
    for case in old['cases']:
        cache.write(output/'selections'/f'{case}.json',selections[case])
        cache.write(output/'references'/f'{case}.json',references[case])
    cache.write(output/'selection_seal.json',dict(files_sha256={str(p.relative_to(output)):cache.digest(p)
        for p in sorted(output.rglob('*')) if p.is_file()}))
    return dict(prepared=str(output),trials=17,samples=85,algorithm_runs=0,provider_calls=0,subject_executions=0)


def verify_selection(prepared):
    prepared=Path(prepared);seal=cache.read(prepared/'selection_seal.json')
    cache.assert_hashes({str(prepared/name):sha for name,sha in seal['files_sha256'].items()})
    protocol=cache.read(prepared/'protocol.json');cache.assert_hashes(protocol['immutable_inputs_sha256'])
    old,_=cache.verify_ready(protocol['cache_prepared'])
    if protocol['cases']!=old['cases'] or protocol['sample_count']!=85:raise ValueError('sample_denominator_changed')
    for case in protocol['cases']:
        original=cache.read(Path(protocol['cache_prepared'])/'selections'/f'{case}.json')
        current=cache.read(prepared/'selections'/f'{case}.json')
        if cache.canonical(original)!=cache.canonical(current):raise ValueError('sample_or_provenance_changed:'+case)
    return protocol


def freeze(prepared):
    prepared=Path(prepared).resolve();protocol=verify_selection(prepared)
    if (prepared/'ready.json').exists():raise ValueError('already_frozen')
    old_snapshot=Path(protocol['cache_prepared'])/'code_snapshot';files={}
    for name,sha in protocol['frozen_cache_code_sha256'].items():
        path=old_snapshot/name
        if cache.digest(path)!=sha:raise ValueError('frozen_dependency_changed:'+name)
        files[name]=path
    for name in protocol['additional_code_files']:
        path=ROOT/name
        if not path.is_file():raise ValueError('code_not_ready:'+name)
        files[name]=path
    for name,path in files.items():
        destination=prepared/'code_snapshot'/name;destination.parent.mkdir(parents=True,exist_ok=True)
        destination.write_bytes(path.read_bytes())
    ready=dict(version=VERSION,protocol_sha256=cache.digest(prepared/'protocol.json'),
        selection_seal_sha256=cache.digest(prepared/'selection_seal.json'),
        code_sha256={name:cache.digest(prepared/'code_snapshot'/name) for name in files},
        worker_script=str(prepared/'code_snapshot'/RUNNER),python_executable=os.path.abspath(sys.executable),
        environment=dict(python=sys.version,packages={p:metadata.version(p) for p in cache.PACKAGES}),
        algorithm_runs=0,provider_calls=0,subject_executions=0)
    cache.write(prepared/'ready.json',ready)
    return dict(ready_sha256=cache.digest(prepared/'ready.json'),code_files=len(files),algorithm_runs=0)


def verify_ready(prepared):
    protocol=verify_selection(prepared);ready=cache.read(Path(prepared)/'ready.json')
    if cache.digest(Path(prepared)/'protocol.json')!=ready['protocol_sha256'] or cache.digest(Path(prepared)/'selection_seal.json')!=ready['selection_seal_sha256']:
        raise ValueError('prepared_protocol_changed')
    cache.assert_hashes({str(Path(prepared)/'code_snapshot'/name):sha for name,sha in ready['code_sha256'].items()})
    if sys.version!=ready['environment']['python'] or any(metadata.version(p)!=v for p,v in ready['environment']['packages'].items()):
        raise ValueError('environment_changed')
    return protocol,ready


def worker(prepared,case,arm,output):
    protocol,_=verify_ready(prepared)
    if case not in protocol['cases'] or arm not in protocol['arms']:raise ValueError('unknown_case_or_arm')
    snapshot=Path(prepared)/'code_snapshot';sys.path.insert(0,str(snapshot))
    selection=cache.read(Path(prepared)/'selections'/f'{case}.json')
    corpus=cache.read(selection['source_paths']['corpus.json']);frontend=cache.read(selection['source_paths']['frontend.json'])
    candidates=selection['candidates'];patch=Path(selection['patch_path']).read_bytes().decode('utf-8')
    before=cache.value_sha([corpus,frontend,candidates,patch]);settings=protocol['arms'][arm]
    module=importlib.import_module(settings['module'])
    if Path(module.__file__).resolve()!=snapshot.joinpath(*settings['module'].split('.')).with_suffix('.py').resolve():
        raise ValueError('module_not_from_frozen_snapshot')
    from relation_search.instrument import _program_edits
    start=time.perf_counter();normalized=[dict(c,edits=_program_edits(c)) for c in candidates]
    analyzer=module.Analyzer(corpus,frontend,patch,**settings['kwargs'])
    records={c['id']:analyzer.evidence(c) for c in normalized};elapsed=time.perf_counter()-start
    if cache.value_sha([corpus,frontend,candidates,patch])!=before:raise ValueError('source_inputs_mutated')
    cache.write(output,dict(case=case,arm=arm,status='ok',candidate_ids=selection['candidate_ids'],
        evidence=records,analysis_wall_seconds=elapsed,source_support=source_counts(records),
        work_counts=getattr(analyzer,'work_counts',{}),input_objects_unchanged=True))


def comparison(reference,observed):
    return dict(complete_json=cache.compare_evidence(reference,observed),
        base_fields=cache.compare_evidence(base_fields(reference),base_fields(observed)))


def summarize(cases,arm):
    rows=[case[arm] for case in cases.values()];okay=[r for r in rows if r['status']=='ok']
    counts=Counter(r['status'] for r in rows);reasons=Counter();correspondence=Counter();bases=Counter();mapping_unknowns=Counter()
    for row in okay:
        support=row['source_support'];reasons.update(support['unknown_reason_instances'])
        correspondence.update(support['correspondence_observation_instances'])
        bases.update(support['correspondence_basis_instances']);mapping_unknowns.update(support['correspondence_unknown_reason_instances'])
    return dict(expected_trials=17,expected_members=85,statuses=dict(counts),completed_members=sum(r['source_support']['evidence_records'] for r in okay),
        unavailable_members=5*(17-len(okay)),analysis_wall_seconds=sum(r['analysis_wall_seconds'] for r in okay),
        worker_wall_seconds=sum(r.get('worker_wall_seconds',0) for r in rows),
        strong=sum(r['source_support']['strong'] for r in okay),may=sum(r['source_support']['may'] for r in okay),
        unknown_members=sum(r['source_support']['unknown_candidates'] for r in okay),
        unknown_reason_instances=dict(reasons),correspondence_observation_instances=dict(correspondence),
        correspondence_basis_instances=dict(bases),correspondence_unknown_reason_instances=dict(mapping_unknowns))


def run(prepared,output):
    prepared=Path(prepared).resolve();output=Path(output).resolve();protocol,ready=verify_ready(prepared)
    if output.exists():raise ValueError('run_directory_already_exists')
    output.mkdir(parents=True,exist_ok=False);plan={case:order(case) for case in protocol['cases']}
    cache.write(output/'run_protocol.json',dict(prepared_ready_sha256=cache.digest(prepared/'ready.json'),
        arm_order=plan,cost=protocol['cost'],provider_calls=0,subject_executions=0))
    environment=dict(os.environ,PYTHONHASHSEED='0',PYTHONDONTWRITEBYTECODE='1');start=time.monotonic();cases={};pairs={}
    for case in protocol['cases']:
        references=cache.read(prepared/'references'/f'{case}.json');rows={};evidence={}
        for arm in plan[case]:
            remaining=protocol['cost']['total_run_wall_seconds']-(time.monotonic()-start)
            if remaining<=0:
                rows[arm]=dict(status='budget_not_started',expected_members=5);continue
            destination=output/case/(arm+'.json');destination.parent.mkdir(parents=True,exist_ok=True)
            command=[ready['python_executable'],'-B',ready['worker_script'],'worker','--prepared',str(prepared),
                '--case',case,'--arm',arm,'--output',str(destination)]
            launched=time.monotonic()
            try:
                completed=subprocess.run(command,cwd=str(prepared/'code_snapshot'),env=environment,
                    capture_output=True,text=True,timeout=min(protocol['cost']['per_worker_wall_seconds'],remaining))
                destination.with_suffix('.stdout').write_text(completed.stdout)
                destination.with_suffix('.stderr').write_text(completed.stderr)
                if completed.returncode==0 and destination.is_file():
                    row=cache.read(destination);evidence[arm]=row['evidence']
                    rows[arm]=dict(status='ok',analysis_wall_seconds=row['analysis_wall_seconds'],
                        source_support=row['source_support'],work_counts=row['work_counts'],
                        frozen_v1=comparison(references['frozen_v1'],row['evidence']),
                        sealed_cached=comparison(references['sealed_cached'],row['evidence']))
                else:rows[arm]=dict(status='worker_error',returncode=completed.returncode,expected_members=5)
            except subprocess.TimeoutExpired:
                rows[arm]=dict(status='timeout',expected_members=5)
            rows[arm]['worker_wall_seconds']=time.monotonic()-launched
            print(cache.json.dumps(dict(case=case,arm=arm,status=rows[arm]['status'])),flush=True)
        cases[case]=rows;pairs[case]={}
        for first,second in [('cached_baseline','repaired_control'),('repaired_control','correspondence_only'),
            ('repaired_control','binder_receiver_only'),('repaired_control','both'),
            ('correspondence_only','both'),('binder_receiver_only','both')]:
            pairs[case][first+'_vs_'+second]=dict(status='ok',comparison=comparison(evidence[first],evidence[second])) \
                if first in evidence and second in evidence else dict(status='unavailable',expected_members=5,comparison=None)
    verify_ready(prepared)
    cache.write(output/'summary.json',dict(cases=cases,aggregate={arm:summarize(cases,arm) for arm in ARM_NAMES},
        pairwise=pairs,trials=17,sample_count=85,run_wall_seconds=time.monotonic()-start,
        interpretation='Source support, exact evidence changes and bounded cost only; no oracle correctness, exposure or detection claims.',
        provider_calls=0,subject_executions=0))
    cache.write(output/'seal.json',dict(files_sha256={str(p.relative_to(output)):cache.digest(p)
        for p in sorted(output.rglob('*')) if p.is_file()}))
    return dict(output=str(output),trials=17,samples=85,provider_calls=0,subject_executions=0)


if __name__=='__main__':
    parser=argparse.ArgumentParser(__doc__);commands=parser.add_subparsers(dest='command',required=True)
    p=commands.add_parser('prepare');p.add_argument('--cache-prepared',type=Path,required=True);p.add_argument('--cache-run',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--worker-seconds',type=float,default=120);p.add_argument('--total-seconds',type=float,default=1200)
    p=commands.add_parser('freeze');p.add_argument('--prepared',type=Path,required=True)
    p=commands.add_parser('run');p.add_argument('--prepared',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p=commands.add_parser('worker');p.add_argument('--prepared',type=Path,required=True);p.add_argument('--case',required=True);p.add_argument('--arm',choices=ARM_NAMES,required=True);p.add_argument('--output',type=Path,required=True)
    arguments=parser.parse_args()
    if arguments.command=='prepare':result=prepare(arguments.cache_prepared,arguments.cache_run,arguments.output,arguments.worker_seconds,arguments.total_seconds)
    elif arguments.command=='freeze':result=freeze(arguments.prepared)
    elif arguments.command=='run':result=run(arguments.prepared,arguments.output)
    else:worker(arguments.prepared,arguments.case,arguments.arm,arguments.output);result={'status':'ok'}
    print(cache.json.dumps(result,sort_keys=True))
