"""Candidate graphs are reparsed before source-anchored obligation scheduling."""
import copy

import pytest

from anchor_retrieval.syntax import Source
from relational_gap.frontend import extract_frontend,to_emitter_corpus
from relation_search.impact_selection import select as original_select
from experimental.modified_observation_impact import Analyzer,map_unchanged_span,select


def setup(code,language='python'):
    path={'python':'test_source.py','go':'source_test.go','typescript':'source.test.ts'}[language]
    source=Source(path,code,language);frontend=extract_frontend([source]);corpus=to_emitter_corpus(frontend)
    return corpus,frontend


def candidate(corpus,before,after,identifier='change',occurrence=0):
    base=next(iter(corpus['tests']));path=corpus['tests'][base]['span']['path']
    source=corpus['sources'][path]['code'].encode();offset=0
    for _ in range(occurrence+1):start=source.index(before.encode(),offset);offset=start+len(before.encode())
    return dict(id=identifier,base_test_id=base,imports=[],edits=[dict(
        span=dict(path=path,start_byte=start,end_byte=offset),before=before,after=after,role='input')])


def evidence(corpus,front,row):return select(corpus,front,[row])['ranking'][0]['evidence']


@pytest.mark.parametrize('language,code,before,after',[
 ('python','def test_case():\n    value = 10\n    assert value == 10\n','    assert','    value = f(g(value))\n    assert'),
 ('go','package sample\nimport "testing"\nfunc TestCase(t *testing.T) { value := 10; if value != 10 { t.Fatal(value) } }','if value','value = f(g(value)); if value'),
 ('typescript',"test('case',()=>{ let value=10; expect(value).toBe(10); });",'expect(value)','value=f(g(value)); expect(value)')])
def test_inserted_nested_calls_create_seeds_absent_in_original_graph(language,code,before,after):
    corpus,front=setup(code,language)
    # A true zero-width statement insertion before the unchanged assertion.
    row=candidate(corpus,before,before)
    row['edits'][0]['after']=after[:-len(before)]
    row['edits'][0]['before']='';row['edits'][0]['span']['end_byte']=row['edits'][0]['span']['start_byte']
    previous=original_select(corpus,front,[row])['ranking'][0]['evidence']
    current=evidence(corpus,front,row)
    assert not previous['obligations']
    local_original=select(corpus,front,[row],graph_source='original')['ranking'][0]['evidence']
    assert not local_original['obligations']
    assert current['obligations']
    assert {'f','g'}<={c['callee'] for c in current['modified_calls']}
    assert {o['observation_id'] for o in current['obligations']}<={q['id'] for q in front['observations']}
    assert all(n['text_basis']=='complete_modified_source_span' for o in current['obligations'] for n in o['path'])


def test_replaced_callee_and_receiver_use_new_local_binding_and_no_old_call():
    corpus,front=setup('''class First:
    def read(self):
        return 10
class Second:
    def alternate(self):
        return 20
def test_case():
    first = First()
    second = Second()
    result = first.read()
    assert result == 10
''')
    row=candidate(corpus,'first.read()','second.alternate()')
    current=evidence(corpus,front,row)
    assert current['obligations']
    assert 'second.alternate' in {c['callee'] for c in current['modified_calls']}
    assert 'first.read' not in {c['callee'] for c in current['modified_calls']}
    assert all('first.read' not in n['text'] for o in current['obligations'] for n in o['path'])
    rebound=next(call for call in current['modified_calls'] if call['callee']=='second.alternate')
    assert rebound['targets'] and all('Second.alternate' in target['function_id'] for target in rebound['targets'])


def test_rebound_receiver_does_not_keep_deleted_old_receiver_dependency():
    corpus,front=setup('''def test_case():
    first = First()
    second = Second()
    first.value = 10
    result = first.read()
    assert result == 10
''')
    field=candidate(corpus,'= 10','= 20');receiver=candidate(corpus,'first.read()','second.read()')
    row=dict(field,edits=[*field['edits'],*receiver['edits']])
    current=evidence(corpus,front,row)
    assert not [o for o in current['obligations'] if o['edit_index']==0]
    assert [o for o in current['obligations'] if o['edit_index']==1]


def test_expected_that_follows_same_input_is_balanced_after_edit():
    corpus,front=setup('def test_case():\n    value = 10\n    result = operation(value)\n    assert result == value\n')
    row=candidate(corpus,'= 10','= 20')
    current=evidence(corpus,front,row)
    assert current['balanced_observation_ids'] and not current['obligations']


def test_unrelated_insertion_does_not_make_an_obligation_or_new_observation():
    corpus,front=setup('def test_case():\n    value = 10\n    assert value == 10\n')
    row=candidate(corpus,'    assert','    assert');edit=row['edits'][0]
    edit.update(before='',after='    unrelated = operation(20)\n');edit['span']['end_byte']=edit['span']['start_byte']
    current=evidence(corpus,front,row)
    assert not current['obligations']
    assert len(current['assertion_alignment'])==1
    assert 'unresolved_modified_call_target:operation' in current['unknowns']


def test_same_port_and_phase_identity_survive_multibyte_shift_and_extra_unrelated_edit():
    corpus,front=setup('''def test_case():
    value = 10
    assert value == 10
    value = 10
    assert value == 10
''')
    one=candidate(corpus,'= 10','= 20','one');two=candidate(corpus,'= 10','= 9999','two')
    insertion=candidate(corpus,'    value','    value')['edits'][0]
    insertion.update(before='',after='    label = "雪"\n');insertion['span']['end_byte']=insertion['span']['start_byte']
    two['edits'].insert(0,insertion)
    a=evidence(corpus,front,one);b=evidence(corpus,front,two)
    assert {(o['observation_id'],o['port_id']) for o in a['obligations']}=={(o['observation_id'],o['port_id']) for o in b['obligations']}
    assert len(a['obligations'])==len(b['obligations'])==1
    assert a['obligations'][0]['modified_assertion_span']!=b['obligations'][0]['modified_assertion_span']
    assert len({row['observation_id'] for row in b['assertion_alignment']})==2


def test_control_paths_are_may_facts_even_for_an_infeasible_branch():
    corpus,front=setup('''def test_case():
    value = 10
    if False:
        value = operation(20)
    assert value == 10
''')
    row=candidate(corpus,'False','True')
    current=evidence(corpus,front,row)
    assert current['obligations'] and 'control_path_feasibility_unproved' in current['unknowns']


def test_deletion_and_parse_error_are_explicit_unknown_and_retain_exploration():
    corpus,front=setup('def test_case():\n    value = operation(10)\n    assert value == 10\n')
    deleted=candidate(corpus,'10','','deleted');invalid=candidate(corpus,'operation(10)','(','invalid')
    result=select(corpus,front,[deleted,invalid],budget=2)
    assert len(result['selected'])==2
    by={r['id']:r['evidence'] for r in result['ranking']}
    assert 'deleted_input_no_modified_value_seed:E0' in by['deleted']['unknowns']
    assert 'modified_owner_parse_error' in by['invalid']['unknowns']


def test_analysis_is_independent_of_input_order_and_label_annotations():
    corpus,front=setup('def test_case():\n    value = 10\n    assert value == 10\n')
    rows=[candidate(corpus,'= 10','= '+str(i),str(i)) for i in (20,30,40)]
    saved=copy.deepcopy((corpus,front,rows));first=select(corpus,front,rows,budget=2)
    annotated=copy.deepcopy(rows[::-1])
    for row in annotated:row.update(evaluation_target=True,oracle_cache={'match':True},runtime_outcome='fail')
    second=select(corpus,front,annotated,budget=2)
    assert first['ranking']==second['ranking']
    assert (corpus,front,rows)==saved


def test_unchanged_span_half_open_alignment_at_both_boundaries():
    original=dict(path='a',start_byte=10,end_byte=20)
    changes=[dict(original_span=dict(path='a',start_byte=10,end_byte=10),before='',after='雪'),
             dict(original_span=dict(path='a',start_byte=20,end_byte=20),before='',after='extra')]
    assert map_unchanged_span(original,changes)==dict(path='a',start_byte=13,end_byte=23)


def test_original_local_control_uses_same_observation_and_port_for_value_edit():
    corpus,front=setup('def test_case():\n    value = 10\n    assert value == 10\n')
    row=candidate(corpus,'= 10','= 20')
    before=select(corpus,front,[row],graph_source='original')['ranking'][0]['evidence']
    after=evidence(corpus,front,row)
    assert {(o['observation_id'],o['port_id']) for o in before['obligations']}=={(o['observation_id'],o['port_id']) for o in after['obligations']}
    assert before['dependence_status']=='original_source_local_may_impact'


def test_multiline_decorator_edit_maps_function_start_not_old_line_or_same_name():
    corpus,front=setup('''@parameterize("value", [
    10,
    20,
])
def test_case(value):
    result = operation(value)
    assert result == 10

def test_case(value):
    result = other(value)
    assert result == 10
''')
    row=candidate(corpus,'[\n    10,\n    20,\n]','[30]')
    call=candidate(corpus,'operation(value)','operation(30)')
    row['edits'].extend(call['edits'])
    current=evidence(corpus,front,row)
    assert 'modified_owner_identity_not_recovered' not in current['unknowns']
    identity=current['test_identity']
    assert identity['original_id']==row['base_test_id']
    assert identity['analyzed_unit_id']!=identity['original_id']
    assert identity['basis']=='exact_mapped_definition_start'
    assert current['obligations']
    original_q={q['id'] for q in front['observations'] if q['test_id']==row['base_test_id']}
    assert {q['observation_id'] for q in current['assertion_alignment']}==original_q
    assert 'other' not in {c['callee'] for c in current['modified_calls']}


def test_replaced_definition_anchor_is_unknown_not_a_same_name_guess():
    corpus,front=setup('def test_case():\n    value = operation(10)\n    assert value == 10\n')
    row=candidate(corpus,'def test_case','def test_other')
    current=evidence(corpus,front,row)
    assert current['eligible'] and not current['obligations']
    assert 'modified_definition_anchor_replaced' in current['unknowns']
