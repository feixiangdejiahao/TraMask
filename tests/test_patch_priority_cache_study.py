"""Qualification for JSON/hash study plumbing; no analyzers or subjects run."""
import hashlib
import sys

import pytest

from scripts import study_patch_priority_cache_equivalence as study


def test_sampling_uses_all_source_members_and_preserves_opaque_provenance():
    pool=[dict(id=str(i),editable=False,provenance={'note':str(i)}) for i in range(9)]
    expected=sorted(pool,key=lambda c:(hashlib.sha256(('T'+c['id']).encode()).hexdigest(),c['id']))[:5]
    chosen=study.sample('T',pool)
    assert chosen==expected==study.sample('T',list(reversed(pool)))
    chosen[0]['provenance']['note']='modified'
    assert pool!=chosen and all(c['provenance']['note']==c['id'] for c in pool)


@pytest.mark.parametrize('size',[0,6])
def test_sample_size_cannot_change_to_unregistered_budget(size):
    with pytest.raises(ValueError):study.sample('T',[{'id':'a'}],size)


def test_duplicate_source_ids_are_not_silently_deduplicated():
    with pytest.raises(ValueError,match='duplicate'):study.sample('T',[{'id':'a'},{'id':'a'}])


def test_arm_order_rotates_primary_only_and_keeps_optional_semantics_separate():
    assert set(study.arm_order('T'))==set(study.PRIMARY_ARMS)
    assert study.arm_order('T',True)==study.arm_order('T')+['v2_receiver']
    assert study.ARMS['v2_cache']['kwargs']=={'disable_receiver_fix':True}
    assert study.ARMS['v3_cache']['kwargs']=={'disable_receiver_fix':True}
    assert not study.ARMS['v2_receiver']['cache_equivalence']


def test_exact_evidence_comparison_sorts_objects_but_preserves_arrays_and_fields():
    original={'a':{'unknowns':['u','v'],'witnesses':[],'may_priority':False}}
    assert study.compare_evidence(original,{'a':dict(reversed(list(original['a'].items())))})['exact_all']
    reordered={'a':dict(original['a'],unknowns=['v','u'])}
    assert not study.compare_evidence(original,reordered)['exact_all']
    absent=study.compare_evidence({'a':{}},{'a':{'present':None}})
    assert absent['mismatched'][0]['differing_top_level_fields']==['present']


def test_missing_and_unexpected_evidence_receive_no_credit():
    result=study.compare_evidence({'a':{},'b':{}},{'a':{},'c':{}})
    assert result['equal_records']==1 and not result['exact_all']
    assert result['missing_ids']==['b'] and result['unexpected_ids']==['c']


def test_source_unknowns_are_reported_without_treating_may_as_strong():
    result=study.support_counts({'a':{'strong_priority':False,'may_priority':True,
        'unknowns':[{'reason':'heap'}],'patch_unknowns':['patch_missing']},'b':{}})
    assert result==dict(evidence_records=2,strong=0,may=1,unknown_candidates=1,
        unknown_reason_instances={'heap':1,'patch_missing':1})


def test_failed_trials_and_records_remain_in_aggregate_denominator():
    okay=dict(status='ok',analysis_wall_seconds=2,worker_total_wall_seconds=3,
        source_support=study.support_counts({'a':{}}),
        reference_equality=study.compare_evidence({'a':{}},{'a':{}}))
    rows={'T1':{'v1':okay},'T2':{'v1':dict(status='analysis_error',worker_total_wall_seconds=4)}}
    result=study.aggregate(rows,{'T1':1,'T2':5},['v1'])['v1']
    assert result['expected_trials']==2 and result['expected_records']==6
    assert result['analysis_error_trials']==1 and result['completed_records']==1
    assert result['reference_equality']['equal_records']==1
    assert result['reference_equality']['missing_records']==5
    assert result['worker_total_wall_seconds']==7
    assert study.aggregate(rows,{'T1':1,'T2':5},['v2_receiver'])['v2_receiver']['reference_equality'] is None


@pytest.fixture
def prepared_fixture(tmp_path,monkeypatch):
    census=tmp_path/'census';inventory=tmp_path/'inventory';root=tmp_path/'code'
    cases=[f'T{i:02d}' for i in range(17)];inputs={}
    for i,case in enumerate(cases):
        folder=inventory/case;patch=tmp_path/(case+'.patch');patch.write_bytes(b'fixture patch\n')
        study.write(folder/'case.json',dict(candidate_patch=str(patch),
            repository_provenance=dict(patch_sha256=study.digest(patch))))
        study.write(folder/'corpus.json',{'fixture_source':'not_parsed'})
        study.write(folder/'frontend.json',{'fixture_frontend':'not_parsed'})
        pool=[dict(id=f'{case}_{j}',program_edits=[],provenance={'source':j}) for j in range(265 if i<14 else 264)]
        study.write(folder/'source_pool.json',dict(candidates=pool))
        for name in ['case.json','corpus.json','frontend.json','source_pool.json']:
            path=folder/name;inputs[str(path)]=study.digest(path)
        inputs[str(patch)]=study.digest(patch)
        # The rank field is deliberately irrelevant to selection and equality.
        study.write(census/case/'strict.json',dict(ranking=[dict(id=c['id'],rank=999-j,
            evidence={'strong_priority':False,'unknowns':[]}) for j,c in enumerate(reversed(pool))]))
    base='fixture.py';(root).mkdir();(root/base).write_bytes(b'# frozen\n')
    (census/'code_snapshot').mkdir();(census/'code_snapshot'/base).write_bytes((root/base).read_bytes())
    study.write(census/'protocol.json',dict(cases=cases,source_inventory=str(inventory),
        code_sha256={base:study.digest(root/base)},input_sha256=inputs))
    study.write(census/'seal.json',dict(files_sha256={str(p.relative_to(census)):study.digest(p)
        for p in census.rglob('*') if p.is_file()}))
    monkeypatch.setattr(study,'FROZEN_V1_SEAL',study.digest(census/'seal.json'))
    monkeypatch.setattr(study,'ROOT',root)
    prepared=tmp_path/'prepared';study.prepare(census,prepared)
    return census,inventory,root,prepared


def test_preparation_freezes_exact_17_by_5_source_selection(prepared_fixture):
    _,_,_,prepared=prepared_fixture
    protocol=study.verify_selection(prepared)
    assert protocol['cases']==[f'T{i:02d}' for i in range(17)]
    assert protocol['input_candidates']==4502 and protocol['sample_count']==85
    assert protocol['run_status'].startswith('not_run')
    assert not (prepared/'ready.json').exists()
    for case in protocol['cases']:
        row=study.read(prepared/'selections'/f'{case}.json')
        assert len(row['candidates'])==5
        assert set(study.read(prepared/'references'/f'{case}.json'))==set(row['candidate_ids'])


def test_changed_source_pool_is_rejected_before_algorithm_import(prepared_fixture):
    _,inventory,_,prepared=prepared_fixture
    path=inventory/'T00'/'source_pool.json';path.write_text('{}')
    with pytest.raises(ValueError,match='immutable_file_changed'):study.verify_selection(prepared)


def test_changed_sample_is_rejected_by_selection_seal(prepared_fixture):
    _,_,_,prepared=prepared_fixture
    path=prepared/'selections'/'T00.json';path.write_text('{}')
    with pytest.raises(ValueError,match='immutable_file_changed'):study.verify_selection(prepared)


def test_freeze_retains_venv_executable_and_only_copies_code(prepared_fixture,monkeypatch):
    _,_,root,prepared=prepared_fixture
    for name in study.NEW_FILES:
        path=root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text('# no analyzer runs\n')
    executable=root/'venv'/'python';executable.parent.mkdir();executable.symlink_to(sys.executable)
    monkeypatch.setattr(study.sys,'executable',str(executable))
    monkeypatch.setattr(study.metadata,'version',lambda name:'fixture')
    frozen=study.freeze(prepared);ready=study.read(prepared/'ready.json')
    assert ready['python_executable']==str(executable)
    assert frozen['algorithm_runs']==0 and ready['algorithm_runs']==0
    assert study.verify_ready(prepared)[1]==ready
    with pytest.raises(ValueError,match='already_frozen'):study.freeze(prepared)
    path=prepared/'code_snapshot'/'fixture.py';path.write_text('# changed')
    with pytest.raises(ValueError,match='immutable_file_changed'):study.verify_ready(prepared)


def test_freeze_cannot_silently_substitute_a_live_semantic_repair(prepared_fixture):
    _,_,root,prepared=prepared_fixture
    (root/'fixture.py').write_text('# repaired')
    with pytest.raises(ValueError,match='live_shared_source_differs'):study.freeze(prepared)
