"""Group rules fixed on generic examples before inspecting pilot coverage."""
import copy

import pytest

from anchor_retrieval.syntax import Source
from relational_gap.frontend import extract_frontend,to_emitter_corpus
from experimental.context_candidate_groups import build_catalogue,schedule,select


def setup(code,language='python'):
    path={'python':'test_groups.py','go':'groups_test.go','typescript':'groups.test.ts'}[language]
    frontend=extract_frontend([Source(path,code,language)])
    return to_emitter_corpus(frontend),frontend


def change(corpus,before,after,identifier,occurrence=0):
    base=next(iter(corpus['tests']));span=corpus['tests'][base]['span']
    data=corpus['sources'][span['path']]['code'].encode();position=span['start_byte']
    for _ in range(occurrence+1):
        start=data.index(before.encode(),position);position=start+len(before.encode())
    return dict(id=identifier,base_test_id=base,operator='source_input',imports=[],edits=[dict(
        span=dict(path=span['path'],start_byte=start,end_byte=position),before=before,after=after)])


@pytest.mark.parametrize('language,code',[
 ('python','def test_case():\n    result = operation(10)\n    assert result == 10\n'),
 ('go','package sample\nimport "testing"\nfunc TestCase(t *testing.T) { result := operation(10); if result != 10 { t.Fatal(result) } }\n'),
 ('typescript',"test('case',()=>{ const result=operation(10); expect(result).toBe(10); });\n")])
def test_literal_alternatives_share_context_with_at_most_four_members(language,code):
    corpus,frontend=setup(code,language)
    variants=[change(corpus,'10',str(value),'v'+str(value)) for value in range(20,29)]
    result=select(corpus,frontend,variants,budget=1)
    assert len(result['catalogue']['contexts'])==1
    assert [len(g['candidate_ids']) for g in result['groups']]==[4,4,1]
    assert result['selected_candidate_count']==4 and len(result['pending_ids'])==5
    assert all(g['max_expectation_revisions']==1 and not g['equivalence_claim'] for g in result['groups'])
    assert {cid for g in result['groups'] for cid in g['candidate_ids']}=={v['id'] for v in variants}


def test_identical_assertion_text_at_distinct_call_phases_does_not_merge():
    corpus,frontend=setup('''def test_case():
    result = operation(10)
    assert result == 10
    result = operation(10)
    assert result == 10
''')
    variants=[change(corpus,'operation(10)','operation(20)','early'),
              change(corpus,'operation(10)','operation(30)','late',occurrence=1)]
    result=select(corpus,frontend,variants)
    assert len(result['catalogue']['contexts'])==2
    contexts=result['catalogue']['contexts']
    assert contexts[0]['footprint']!=contexts[1]['footprint']


def test_changed_receiver_and_changed_callee_names_cannot_merge():
    corpus,frontend=setup('''def test_case():
    left = First()
    right = Second()
    result = left.read(10)
    assert result == 10
''')
    variants=[change(corpus,'left.read','right.read','other_receiver'),
              change(corpus,'left.read','left.other','other_callee'),
              change(corpus,'left.read','left.third','third_callee')]
    result=select(corpus,frontend,variants)
    assert len(result['catalogue']['contexts'])==3
    assert all(len(g['candidate_ids'])==1 for g in result['groups'])


def test_explicit_observation_focus_keeps_same_edited_input_in_distinct_contexts():
    corpus,frontend=setup('''def test_case():
    number = 10
    first = operation(number)
    assert first == 10
    second = operation(number)
    assert second == 10
''')
    a=change(corpus,'10','20','first');b=change(corpus,'10','30','second')
    a['oracle']=dict(target_assertion_id=frontend['observations'][0]['id'])
    b['oracle']=dict(target_assertion_id=frontend['observations'][1]['id'])
    result=select(corpus,frontend,[a,b])
    assert len(result['catalogue']['contexts'])==2


@pytest.mark.parametrize('policy',['shape','impact'])
def test_cross_round_fairness_and_retention_serve_each_candidate_once(policy):
    corpus,frontend=setup('''def test_case():
    left = operation(10)
    assert left == 10
    right = alternate(11)
    assert right == 11
''')
    variants=[change(corpus,'10',str(i),'left'+str(i)) for i in range(20,30)]
    variants += [change(corpus,'11',str(i),'right'+str(i)) for i in range(40,45)]
    previous=None;shown=[];context_order=[]
    for iteration in range(6):
        result=select(corpus,frontend,variants if iteration==0 else [],budget=1,policy=policy,previous=previous)
        shown.extend(result['selected_candidate_ids'])
        context_order.extend(g['context_id'] for g in result['selected_groups'])
        previous=result['frontier']
    assert len(shown)==len(set(shown))==15
    assert set(shown)=={c['id'] for c in variants}
    assert context_order[0]!=context_order[1]
    assert result['pending_ids']==[]


def test_zero_budget_preserves_every_candidate_and_input_order_does_not_choose():
    corpus,frontend=setup('def test_case():\n    assert operation(10) == 10\n')
    variants=[change(corpus,'10',str(i),'id'+str(i)) for i in range(20,27)]
    original=copy.deepcopy(variants)
    forward=select(corpus,frontend,variants,budget=0)
    reverse=select(corpus,frontend,list(reversed(variants)),budget=0)
    assert forward['groups']==reverse['groups']
    assert forward['selected_candidate_ids']==[]
    assert set(forward['pending_ids'])=={c['id'] for c in variants}
    assert variants==original


def test_changed_source_material_is_rejected_on_resume():
    corpus,frontend=setup('def test_case():\n    assert operation(10) == 10\n')
    candidate=change(corpus,'10','20','same')
    state=select(corpus,frontend,[candidate],budget=0)['frontier']
    changed=copy.deepcopy(candidate);changed['edits'][0]['after']='99'
    with pytest.raises(ValueError,match='changed source material'):
        select(corpus,frontend,[changed],previous=state)


def test_evaluation_annotations_do_not_affect_grouping_or_scheduling():
    corpus,frontend=setup('def test_case():\n    assert operation(10) == 10\n')
    variants=[change(corpus,'10',str(i),'v'+str(i)) for i in range(20,27)]
    annotated=copy.deepcopy(variants)
    for i,candidate in enumerate(annotated):
        candidate.update(evaluation={'target':i==5},oracle_cache={'hit':True},runtime_outcome='FAIL')
    first=select(corpus,frontend,variants);second=select(corpus,frontend,annotated)
    assert first['groups']==second['groups']
    assert first['catalogue']['contexts']==second['catalogue']['contexts']
    assert first['catalogue']['candidate_info']==second['catalogue']['candidate_info']


def test_ineligible_observation_does_not_disappear_from_frontier():
    corpus,frontend=setup('def test_case():\n    result = operation(10)\n    print(result)\n')
    candidate=change(corpus,'10','20','output_only')
    result=select(corpus,frontend,[candidate])
    assert result['selected_candidate_ids']==[]
    assert result['pending_ids']==result['ineligible_ids']==['output_only']
