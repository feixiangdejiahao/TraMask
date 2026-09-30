"""Source-study plumbing qualification; no analyzers or subjects run."""
import copy

import pytest

from scripts import study_source_repairs as study


def test_ablation_flags_are_explicit_and_only_change_the_intended_repair():
    assert study.ARMS['cached_baseline']['kwargs']=={'disable_receiver_fix':True}
    assert study.ARMS['repaired_control']['kwargs']==dict(repair_correspondence=False,repair_arguments=False,disable_receiver_fix=True)
    assert study.ARMS['correspondence_only']['kwargs']==dict(repair_correspondence=True,repair_arguments=False,disable_receiver_fix=True)
    assert study.ARMS['binder_receiver_only']['kwargs']==dict(repair_correspondence=False,repair_arguments=True,disable_receiver_fix=False)
    assert study.ARMS['both']['kwargs']==dict(repair_correspondence=True,repair_arguments=True,disable_receiver_fix=False)


def test_all_five_arms_participate_in_source_only_rotation():
    assert set(study.order('T'))==set(study.ARM_NAMES)
    assert study.order('T')==study.order('T')


def test_full_json_change_is_not_hidden_by_supplemental_base_projection():
    before={'a':{'strong_priority':False,'unknowns':['u']}}
    after={'a':dict(before['a'],source_repairs={'observations':[{'status':'corresponding'}]})}
    original=copy.deepcopy(after);result=study.comparison(before,after)
    assert not result['complete_json']['exact_all'] and result['base_fields']['exact_all']
    assert result['complete_json']['mismatched'][0]['differing_top_level_fields']==['source_repairs']
    assert original==after
    after['a']['unknowns']=[]
    assert not study.comparison(before,after)['base_fields']['exact_all']


def test_correspondence_facts_and_unknown_instances_are_preserved_separately():
    records={'a':dict(strong_priority=False,may_priority=True,unknowns=['dispatch_unknown'],
        source_repairs={'observations':[dict(status='corresponding',basis='actual_expression_edit'),
            dict(status='unknown',reason='crossing_boundary')]})}
    result=study.source_counts(records)
    assert result['strong']==0 and result['may']==1 and result['unknown_candidates']==1
    assert result['correspondence_observation_instances']=={'corresponding':1,'unknown':1}
    assert result['correspondence_unknown_reason_instances']=={'crossing_boundary':1}


def test_errors_timeouts_and_unstarted_trials_stay_in_fixed_denominator():
    rows={f'T{i}':{'both':dict(status='budget_not_started',expected_members=5)} for i in range(17)}
    rows['T0']['both']=dict(status='timeout',worker_wall_seconds=120)
    rows['T1']['both']=dict(status='worker_error',worker_wall_seconds=1)
    rows['T2']['both']=dict(status='ok',analysis_wall_seconds=2,worker_wall_seconds=3,
        source_support=study.source_counts({str(i):{} for i in range(5)}))
    result=study.summarize(rows,'both')
    assert result['expected_trials']==17 and result['expected_members']==85
    assert result['completed_members']==5 and result['unavailable_members']==80
    assert result['strong']==0 and result['may']==0
    assert result['statuses']==dict(budget_not_started=14,timeout=1,worker_error=1,ok=1)
    assert result['worker_wall_seconds']==124


@pytest.fixture
def prepared_fixture(tmp_path,monkeypatch):
    cache_prepared=tmp_path/'cache';cache_run=tmp_path/'run';root=tmp_path/'live'
    cases=[f'T{i:02d}' for i in range(17)]
    original=dict(cases=cases,sample_count=85,input_candidates=4502,immutable_inputs_sha256={})
    ready=dict(code_sha256={'frozen.py':'unused'})
    for case in cases:
        candidates=[dict(id=f'{case}_{j}',provenance={'opaque':j}) for j in range(5)]
        evidence={c['id']:dict(strong_priority=False,unknowns=[]) for c in candidates}
        study.cache.write(cache_prepared/'selections'/f'{case}.json',dict(case=case,
            candidate_ids=[c['id'] for c in candidates],candidates=candidates))
        study.cache.write(cache_prepared/'references'/f'{case}.json',evidence)
        study.cache.write(cache_run/case/'v3_cache.json',dict(status='ok',evidence=evidence))
    study.cache.write(cache_prepared/'protocol.json',original)
    study.cache.write(cache_prepared/'selection_seal.json',{'fixture':'source only'})
    snapshot=cache_prepared/'code_snapshot';snapshot.mkdir();(snapshot/'frozen.py').write_text('# frozen')
    ready['code_sha256']['frozen.py']=study.cache.digest(snapshot/'frozen.py')
    study.cache.write(cache_prepared/'ready.json',ready)
    study.cache.write(cache_run/'seal.json',dict(files_sha256={str(p.relative_to(cache_run)):study.cache.digest(p)
        for p in cache_run.rglob('*') if p.is_file()}))
    monkeypatch.setattr(study,'CACHE_READY_SHA',study.cache.digest(cache_prepared/'ready.json'))
    monkeypatch.setattr(study,'CACHE_RUN_SEAL_SHA',study.cache.digest(cache_run/'seal.json'))
    monkeypatch.setattr(study.cache,'verify_ready',lambda path:(original,ready))
    monkeypatch.setattr(study,'ROOT',root)
    output=tmp_path/'prepared';study.prepare(cache_prepared,cache_run,output)
    return cache_prepared,cache_run,root,output


def test_preparation_copies_exact_previous_sample_instead_of_reselecting(prepared_fixture):
    old,_,_,prepared=prepared_fixture;protocol=study.verify_selection(prepared)
    assert protocol['sample_count']==85 and protocol['cost']['retries']==0
    assert protocol['cost']['per_worker_wall_seconds']==120
    assert protocol['cost']['total_run_wall_seconds']==1200
    for case in protocol['cases']:
        assert study.cache.read(old/'selections'/f'{case}.json')==study.cache.read(prepared/'selections'/f'{case}.json')
    assert not (prepared/'ready.json').exists()


@pytest.mark.parametrize('change',['selection','reference'])
def test_prepared_sample_or_reference_tampering_is_rejected(prepared_fixture,change):
    _,_,_,prepared=prepared_fixture
    folder='selections' if change=='selection' else 'references'
    (prepared/folder/'T00.json').write_text('{}')
    with pytest.raises(ValueError,match='immutable_file_changed'):study.verify_selection(prepared)


def test_old_cached_reference_must_equal_the_frozen_source_evidence(prepared_fixture,tmp_path,monkeypatch):
    old,run,_,_=prepared_fixture
    path=run/'T00'/'v3_cache.json';record=study.cache.read(path)
    record['evidence']['T00_0']['strong_priority']=True;study.cache.write(path,record)
    seal=study.cache.read(run/'seal.json');seal['files_sha256']['T00/v3_cache.json']=study.cache.digest(path)
    study.cache.write(run/'seal.json',seal);monkeypatch.setattr(study,'CACHE_RUN_SEAL_SHA',study.cache.digest(run/'seal.json'))
    with pytest.raises(ValueError,match='cache_reference_not_exact'):
        study.prepare(old,run,tmp_path/'different')


@pytest.mark.parametrize('worker,total',[(121,1200),(120,1201),(120,119),(0,1200)])
def test_bound_cannot_be_extended_or_disabled(prepared_fixture,tmp_path,worker,total):
    old,run,_,_=prepared_fixture
    with pytest.raises(ValueError,match='cost_bounds'):study.prepare(old,run,tmp_path/'other',worker,total)


def test_freeze_copies_original_dependencies_without_live_semantic_substitution(prepared_fixture,monkeypatch):
    old,_,root,prepared=prepared_fixture
    for name in study.NEW_FILES:
        path=root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text('# source only\n')
    monkeypatch.setattr(study.metadata,'version',lambda package:'fixture')
    result=study.freeze(prepared)
    assert result['algorithm_runs']==0
    assert (prepared/'code_snapshot'/'frozen.py').read_bytes()==(old/'code_snapshot'/'frozen.py').read_bytes()
    assert study.verify_ready(prepared)[1]['algorithm_runs']==0
    (prepared/'code_snapshot'/'frozen.py').write_text('# changed')
    with pytest.raises(ValueError,match='immutable_file_changed'):study.verify_ready(prepared)
