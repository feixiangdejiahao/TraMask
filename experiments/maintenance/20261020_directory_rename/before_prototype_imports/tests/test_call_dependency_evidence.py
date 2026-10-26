import pytest
from anchor_retrieval.syntax import Source
from relational_gap.frontend import extract_frontend,to_emitter_corpus
from experimental.call_dependency_evidence import candidate_evidence,render_evidence


def setup(language,code,before,after):
    path={'python':'test_evidence.py','go':'evidence_test.go','typescript':'evidence.test.ts'}[language]
    source=Source(path,code,language)
    frontend=extract_frontend([source]);corpus=to_emitter_corpus(frontend)
    test_id=next(iter(corpus['tests']))
    start=code.index(before,corpus['tests'][test_id]['span']['start_byte'])
    candidate=dict(id='unlabeled_candidate',base_test_id=test_id,imports=[],source_test_ids=[],edits=[dict(
        span=dict(path=path,start_byte=start,end_byte=start+len(before)),before=before,after=after)])
    return corpus,frontend,candidate


@pytest.mark.parametrize('language,code,before,after',[
    ('python','def twice(value): return value*2\ndef test_case():\n    input = 1\n    result = twice(input)\n    assert result == 2\n','1','3'),
    ('go','package demo\nimport "testing"\nfunc twice(value int) int { return value*2 }\nfunc TestCase(t *testing.T) {\n input := 1\n result := twice(input)\n if result != 2 { t.Fatal(result) }\n}\n','1','3'),
    ('typescript',"function twice(value: number) { return value*2; }\ntest('case',()=> { const input = 1; const result = twice(input); expect(result).toBe(2); });\n",'1','3'),
])
def test_three_languages_link_setup_edit_actual_formal_and_original_q(language,code,before,after):
    corpus,frontend,candidate=setup(language,code,before,after)
    evidence=candidate_evidence(corpus,frontend,candidate)
    call=next(row for row in frontend['calls'] if row['callee']=='twice')
    assert call['id'] in evidence['seed_call_ids']
    assert evidence['related_observation_ids']
    assert any(edge['kind']=='original_actual_formal' and edge['parameter']=='value' for edge in evidence['edges'])
    assert any(edge['kind']=='original_value_use' and edge['target']=='C:'+call['id'] for edge in evidence['edges'])
    assert any(edge['kind']=='original_static_slice_may_dependence' for edge in evidence['edges'])
    rendered=render_evidence(evidence)
    assert 'twice' in rendered and 'value' in rendered and '\n=>\n3\n' in rendered
    assert render_evidence(evidence)==rendered
    assert evidence['complete_slice'] is False and evidence['modified_bindings_recomputed'] is False


def test_receiver_binding_is_shown_but_object_identity_is_not_claimed():
    corpus,frontend,candidate=setup('python','''class Box:
    def step(self, value): return value*2
def test_case():
    box = Box()
    result = box.step(1)
    assert result == 2
''','1','3')
    evidence=candidate_evidence(corpus,frontend,candidate)
    assert any(row['kind']=='receiver' and row['code']=='box' for row in evidence['nodes'])
    links=[edge for edge in evidence['edges'] if edge['kind']=='original_local_binding' and edge['source'].startswith('R:')]
    assert links and all(edge['object_identity']=='unknown' for edge in links)
    assert 'box = Box()' in render_evidence(evidence)


def test_new_or_edited_callee_does_not_reuse_old_target_or_argument_bindings():
    corpus,frontend,candidate=setup('python','''def original(value): return value
def alternate(value): return value + 1
def test_case():
    result = original(1)
    assert result == 1
''','original','alternate')
    evidence=candidate_evidence(corpus,frontend,candidate)
    old=next(row for row in frontend['calls'] if row['callee']=='original')
    assert any(row['reason']=='new_callee_unresolved' and row.get('callee')=='alternate' for row in evidence['unknowns'])
    assert any(row['reason']=='modified_callee_binding_not_reused' and row.get('call_id')==old['id'] for row in evidence['unknowns'])
    assert not any(edge['kind']=='original_source_target' and edge['source']=='C:'+old['id'] for edge in evidence['edges'])
    assert not any(edge['kind']=='original_actual_formal' and edge.get('call_id')==old['id'] for edge in evidence['edges'])


def test_prefix_insertion_at_callee_boundary_invalidates_original_binding():
    corpus,frontend,candidate=setup('python','def original(value): return value\ndef test_case():\n    assert original(1) == 1\n','original','original')
    edit=candidate['edits'][0]
    edit['span']['end_byte']=edit['span']['start_byte']
    edit['before']='';edit['after']='receiver.'
    evidence=candidate_evidence(corpus,frontend,candidate)
    call=next(row for row in frontend['calls'] if row['callee']=='original')
    assert any(row['reason']=='modified_callee_binding_not_reused' and row.get('call_id')==call['id'] for row in evidence['unknowns'])
    assert not any(edge['kind']=='original_source_target' and edge['source']=='C:'+call['id'] for edge in evidence['edges'])


def test_edited_receiver_definition_does_not_inherit_previous_target():
    corpus,frontend,candidate=setup('python','''class Box:
    def step(self, value): return value*2
def test_case():
    box = Box()
    result = box.step(1)
    assert result == 2
''','Box()','factory()')
    evidence=candidate_evidence(corpus,frontend,candidate)
    call=next(row for row in frontend['calls'] if row['callee']=='box.step')
    assert any(row['reason']=='modified_callee_binding_not_reused' and row.get('call_id')==call['id'] and row['receiver_definition_edited'] for row in evidence['unknowns'])
    assert not any(edge['kind']=='original_source_target' and edge['source']=='C:'+call['id'] for edge in evidence['edges'])


def test_render_deduplicates_contained_code_without_losing_node_positions_or_edges():
    evidence=dict(nodes=[dict(id='outer',kind='declaration',span=dict(path='x.py',start_byte=0,end_byte=20),code='unique declaration'),
                        dict(id='inner',kind='formal',span=dict(path='x.py',start_byte=4,end_byte=9),code='nested text')],
                  edges=[dict(source='inner',target='outer',kind='original_binding')],unknowns=[])
    rendered=render_evidence(evidence)
    assert rendered.count('unique declaration')==1 and 'nested text' not in rendered
    assert 'inner [formal] x.py:4..9' in rendered and 'source excerpt: outer' in rendered
    assert 'inner --original_binding--> outer' in rendered
