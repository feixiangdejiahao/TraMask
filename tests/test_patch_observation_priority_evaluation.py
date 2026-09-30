import pytest
from scripts.evaluate_patch_observation_priority import source_program_signature, exposure, aggregate


def candidate(after='2'):
    return {'base_test_id':'t','edits':[{'span':{'path':'t.py','start_byte':10,'end_byte':11},'before':'1','after':after,'role':'input'}]}


def test_exact_edit_source_signature_is_id_independent():
    a=candidate();b=dict(a,id='revision-id',score=999)
    assert source_program_signature(a)==source_program_signature(b)
    assert source_program_signature(a)!=source_program_signature(candidate('3'))


def test_witness_uses_explicit_pre_oracle_snapshot():
    a=candidate();revised=dict(a,program_edits=a['edits'],edits=[dict(a['edits'][0],role='semantic_expected',after='99')])
    assert source_program_signature(a)==source_program_signature(revised,recorded_program_edits=True)
    with pytest.raises(ValueError,match='original_program_snapshot_missing'):
        source_program_signature(a,recorded_program_edits=True)
    with pytest.raises(ValueError,match='oracle_expectation'):
        source_program_signature(revised)


def test_exposure_keeps_absent_targets_and_budget_boundary():
    ranking=[{'id':str(i),'rank':i} for i in range(1,20)]
    assert exposure(ranking,['16'])['hit_at_budget']
    assert not exposure(ranking,['17'])['hit_at_budget']
    assert exposure(ranking,['missing'])==dict(available=False,hit_at_budget=False,best_rank=None,matches=[])


def test_aggregate_reports_full_and_available_denominators():
    rows=[{'source_pool_available':True,'arm':{'hit_at_budget':True}},
          {'source_pool_available':True,'arm':{'hit_at_budget':False}},
          {'source_pool_available':False,'arm':{'hit_at_budget':False}}]
    result=aggregate(rows,'arm')
    assert result['hits']==1
    assert result['all_trial_denominator']==3
    assert result['available_trial_denominator']==2
    assert result['available_trial_rate']==.5


def write_case(tmp_path):
    import json
    p=tmp_path/'C';p.mkdir()
    ordered={'shape':['a','b','c','d'],'strict':['d','a','b','c'],'may':['b','d','a','c']}
    eligibility={'a':True,'b':False,'c':True,'d':True}
    baseline={cid:i+1 for i,cid in enumerate(ordered['shape'])}
    for arm,ids in ordered.items():
        ranking=[]
        for i,cid in enumerate(ids):
            row=dict(id=cid,rank=i+1)
            if arm!='shape':
                row.update(baseline_rank=baseline[cid],evidence={'strong_priority':cid=='d','may_priority':cid in {'b','d'},'unknowns':['unproved']})
            ranking.append(row)
        (p/(arm+'.json')).write_text(json.dumps({'ranking':ranking,'selected':[{'id':cid} for cid in ids]}))
        filtered=[cid for cid in ids if eligibility[cid]]
        (p/(arm+'_eligible.json')).write_text(json.dumps({'selected_ids':filtered,'complete_ranking':[{'id':cid} for cid in filtered]}))
    (p/'eligibility.json').write_text(json.dumps([{'id':cid,'eligible':value} for cid,value in eligibility.items()]))
    return p


def test_independent_rank_check_preserves_unknowns_and_shared_eligibility(tmp_path):
    from scripts.evaluate_patch_observation_priority import verify_rank_case
    write_case(tmp_path)
    result=verify_rank_case(tmp_path,'C',['a','b','c','d'])
    assert result['candidates']==4
    assert result['eligibility_count']==3
    assert result['cross_mode_evidence_exact']


@pytest.mark.parametrize('damage', ['selection','baseline','eligibility'])
def test_rank_audit_rejects_corrupt_prefix_binding(tmp_path,damage):
    import json
    from scripts.evaluate_patch_observation_priority import verify_rank_case
    p=write_case(tmp_path)
    if damage=='eligibility':
        path=p/'may_eligible.json';value=json.loads(path.read_text());value['selected_ids']=['d']
    else:
        path=p/'may.json';value=json.loads(path.read_text())
        if damage=='selection':value['selected'].pop()
        else:value['ranking'][0]['baseline_rank']=1
    path.write_text(json.dumps(value))
    with pytest.raises(ValueError):verify_rank_case(tmp_path,'C',['a','b','c','d'])


def test_preview_matches_identical_programs_with_different_edit_windows():
    from scripts.evaluate_patch_observation_priority import preview_signature
    code='def test_x():\n    assert f(1) == 2\n'
    corpus={'language':'python','sources':{'t.py':{'code':code}},'tests':{'t':{'span':{'path':'t.py','start_byte':0,'end_byte':len(code)}}}}
    scalar=code.index('1');call=code.index('f(1)')
    a={'base_test_id':'t','edits':[{'span':{'path':'t.py','start_byte':scalar,'end_byte':scalar+1},'before':'1','after':'3'}]}
    b={'base_test_id':'t','edits':[{'span':{'path':'t.py','start_byte':call,'end_byte':call+4},'before':'f(1)','after':'f(3)'}]}
    assert source_program_signature(a)!=source_program_signature(b)
    assert preview_signature(corpus,a)==preview_signature(corpus,b)
    # Oracle edits are excluded from original input material, never calibrated
    # against buggy runtime results.
    expected=code.index('2');revised=dict(a,edits=a['edits']+[{'span':{'path':'t.py','start_byte':expected,'end_byte':expected+1},'before':'2','after':'999','role':'semantic_expected'}])
    assert preview_signature(corpus,a)==preview_signature(corpus,revised)
    changed_import=dict(a,imports=[{'name':'other','module':'different'}])
    assert preview_signature(corpus,a)!=preview_signature(corpus,changed_import)
