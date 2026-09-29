"""Semantic boundary tests for candidate-specific input evidence."""
import copy
import json

import pytest

from anchor_retrieval.syntax import Source
from relational_gap.frontend import extract_frontend, to_emitter_corpus
from relation_search.oracle_evidence import build_evidence


def setup(language, code, before, after, extra=None, test_name=None):
    path = {'python': 'tests/test_evidence.py', 'go': 'evidence_test.go', 'typescript': 'tests/evidence.test.ts'}[language]
    sources = [Source(path, code, language)] + [Source(p, c, language) for p,c in (extra or {}).items()]
    frontend = extract_frontend(sources)
    corpus = to_emitter_corpus(frontend)
    test_id = next(tid for tid, row in corpus['tests'].items() if test_name is None or row['name'] == test_name)
    span = corpus['tests'][test_id]['span']
    data = code.encode()
    start = data.index(before.encode(), span['start_byte'])
    candidate = dict(id='unlabeled', base_test_id=test_id, imports=[], source_test_ids=[], edits=[dict(
        span=dict(path=path, start_byte=start, end_byte=start+len(before.encode())), before=before, after=after)])
    return corpus, frontend, candidate


@pytest.mark.parametrize('language,code', [
    ('python', 'def twice(value): return value * 2\ndef test_case():\n    input = 1\n    result = twice(input)\n    assert result == 2\n'),
    ('go', 'package demo\nimport "testing"\nfunc twice(value int) int { return value*2 }\nfunc TestCase(t *testing.T) { input := 1; result := twice(input); if result != 2 { t.Fatal(result) } }\n'),
    ('typescript', "function twice(value: number) { return value*2; }\ntest('case', () => { const input = 1; const result = twice(input); expect(result).toBe(2); });\n"),
])
def test_recomputed_value_dependencies_and_actual_formal_across_languages(language, code):
    c,f,k = setup(language, code, '1', '3')
    result = build_evidence(c,f,k)
    call = next(row for row in result['calls'] if row['callee'] == 'twice')
    assert call['seed'] and call['related_assertions']
    assert call['actual_formal'][0]['parameter'] == 'value'
    assert result['modified_bindings_recomputed'] is True
    assert result['complete_slice'] is False
    assert result['status'] == 'ready'
    assert build_evidence(c,f,k) == result
    assert c['sources'][k['edits'][0]['span']['path']]['code'] == code


def test_callee_change_rebinds_to_new_declaration_and_new_formal():
    c,f,k = setup('python', '''def original(left): return left
def alternate(right): return right + 1
def test_case():
    assert original(1) == 1
''', 'original', 'alternate')
    result = build_evidence(c,f,k)
    call = next(row for row in result['calls'] if row['callee'] == 'alternate')
    assert call['targets'][0]['function_id'].endswith(':alternate')
    assert call['actual_formal'][0]['parameter'] == 'right'
    assert 'def alternate(right)' in result['rendered']
    assert 'def original(left)' not in result['rendered']


def test_unknown_changed_receiver_does_not_reuse_old_class_method():
    c,f,k = setup('python', '''class Box:
    def read(self): return 1
def test_case():
    box = Box()
    assert box.read() == 1
''', 'Box()', 'factory()')
    result = build_evidence(c,f,k)
    call = next(row for row in result['calls'] if row['callee'] == 'box.read')
    assert not call['targets']
    assert any(u['reason'] == 'modified_callee_unresolved_or_ambiguous' and u['callee'] == 'box.read' for u in result['unknowns'])


@pytest.mark.parametrize('language,code,extra,module,name,after', [
    ('python', 'def test_case():\n    assert original(1) == 1\n', {'pkg/ops.py': 'def replacement(value): return value + 1\n'}, 'pkg.ops', 'replacement', 'generated_alias'),
    ('typescript', "test('case', () => { expect(original(1)).toBe(1); });\n", {'src/ops.ts': 'export function replacement(value: number) { return value + 1; }\n'}, '../src/ops', 'replacement', 'generated_alias'),
])
def test_new_import_alias_is_bound_to_actual_module(language,code,extra,module,name,after):
    c,f,k = setup(language, code, 'original', after, extra)
    k['imports'] = [dict(name=after, module=module, imported_name=name, source_path=k['edits'][0]['span']['path'])]
    result = build_evidence(c,f,k)
    call = next(row for row in result['calls'] if row['callee'] == after)
    assert call['targets'][0]['function_id'].endswith(':replacement')
    assert call['actual_formal'][0]['parameter'] == 'value'
    assert 'return value + 1' in result['rendered']


def test_relative_ts_donor_import_is_rebased_before_resolution():
    c,f,k = setup('typescript', "test('case', () => { expect(original(1)).toBe(1); });\n", 'original', 'synthetic',
                 {'deep/ops.ts': 'export function replacement(value: number) { return value + 1; }\n',
                  'deep/tests/donor.test.ts': "test('donor', () => { expect(1).toBe(1); });\n"}, test_name='case')
    k['imports'] = [dict(name='synthetic', module='../ops', imported_name='replacement', source_path='deep/tests/donor.test.ts')]
    result = build_evidence(c,f,k)
    call = next(row for row in result['calls'] if row['callee'] == 'synthetic')
    assert call['targets'][0]['function_id'] == 'deep/ops.ts:1:replacement'


def test_edited_field_store_links_same_bound_receiver_to_observation():
    c,f,k = setup('python', '''class Box:
    def read(self): return self.value
def test_case():
    box = Box()
    box.value = 1
    result = box.read()
    assert result == 1
''', 'value = 1', 'value = 3')
    result = build_evidence(c,f,k)
    edges = [e for e in result['edges'] if e['kind'] == 'same_local_binding_after_field_write_may']
    assert edges and edges[0]['field'] == 'value'
    call = next(row for row in result['calls'] if row['callee'] == 'box.read')
    assert call['seed'] and call['related_assertions']
    assert 'return self.value' in result['rendered']


@pytest.mark.parametrize('replacement', ['other = Box()', 'box = Box()'])
def test_field_name_does_not_conflate_different_or_reassigned_receivers(replacement):
    receiver = 'other' if replacement.startswith('other') else 'box'
    c,f,k = setup('python', f'''class Box:
    def read(self): return self.value
def test_case():
    box = Box()
    box.value = 1
    {replacement}
    assert {receiver}.read() == 1
''', 'value = 1', 'value = 3')
    result = build_evidence(c,f,k)
    assert not [e for e in result['edges'] if e['kind'] == 'same_local_binding_after_field_write_may']


def test_exact_changed_argument_retrieves_complete_source_control():
    c,f,k = setup('python', '''def decode(value): return value
def test_case():
    assert decode("a") == "a"
def test_other():
    context = "complete donor setup"
    assert decode("b") == "b"
''', '"a"', '"b"', test_name='test_case')
    result = build_evidence(c,f,k)
    assert any(row['reason'] == 'same_resolved_callee_and_changed_argument' for row in result['controls'])
    contexts = [row['code'] for row in result['declarations'] if 'source_control_test' in row['roles']]
    assert len(contexts) == 1
    assert 'complete donor setup' in contexts[0] and 'assert decode("b") == "b"' in contexts[0]


def test_budget_is_explicit_without_truncating_any_declaration():
    c,f,k = setup('python', 'def twice(value): return value * 2\ndef test_case():\n    assert twice(1) == 2\n', '1','3')
    full = build_evidence(c,f,k)
    limited = build_evidence(c,f,k,max_bytes=10)
    assert limited['status'] == 'over_budget'
    assert limited['rendered'] == full['rendered']
    assert limited['declarations'] == full['declarations']


def test_runtime_probe_edits_are_removed_using_canonical_program_snapshot():
    c,f,k = setup('python', 'def twice(value): return value * 2\ndef test_case():\n    assert twice(1) == 2\n', '1','3')
    plain = build_evidence(c,f,k)
    k['program_edits'] = copy.deepcopy(k['edits'])
    k['instrumentation'] = dict(status='instrumented')
    k['edits'][0]['after'] = 'probe_helper(3)'
    instrumented = build_evidence(c,f,k)
    assert instrumented == plain
    assert 'probe_helper' not in instrumented['rendered']


def test_invalid_original_source_edit_is_rejected():
    c,f,k = setup('python', 'def test_case():\n    assert 1 == 1\n','1','3')
    k['edits'][0]['before'] = 'wrong'
    with pytest.raises(ValueError, match='does not match original'):
        build_evidence(c,f,k)


def test_go_alias_requires_exact_module_path_not_just_package_name():
    code = 'package demo\nimport "testing"\nfunc TestCase(t *testing.T) { result := missing(1); if result != 1 { t.Fatal(result) } }\n'
    c,f,k = setup('go', code, 'missing', 'library.Compute',
                 {'lib/ops.go':'package lib\nfunc Compute(value int) int { return value + 1 }\n'})
    k['imports'] = [dict(name='library',module='example.org/project/lib', imported_name=None)]
    f['module_resolution']['go_modules'] = {'':'example.org/project'}
    result = build_evidence(c,f,k)
    call = next(row for row in result['calls'] if row['callee']=='library.Compute')
    assert call['targets'][0]['function_id']=='lib/ops.go:2:Compute'
    assert call['actual_formal'][0]['parameter']=='value'
    k['imports'][0]['module']='different.org/project/lib'
    result = build_evidence(c,f,k)
    call = next(row for row in result['calls'] if row['callee']=='library.Compute')
    assert not call['targets']


def test_local_function_passed_to_external_api_is_shown_with_unknown_invocation():
    c,f,k = setup('python', '''def grow(value):
    return value + 1
def test_case():
    result = external_executor(grow, 1)
    assert result == 2
''', '1', '3')
    result = build_evidence(c,f,k)
    refs = result['function_valued_arguments']
    assert refs and refs[0]['argument'] == 'grow'
    assert refs[0]['invocation'].startswith('unknown')
    assert any('function_valued_argument_declaration' in d['roles'] and 'return value + 1' in d['code'] for d in result['declarations'])


def test_rebound_callback_name_does_not_inherit_module_function_declaration():
    c,f,k = setup('python', '''def grow(value): return value + 1
def test_case():
    grow = factory()
    result = external_executor(grow, 1)
    assert result == 2
''', '1', '3')
    result = build_evidence(c,f,k)
    assert not result['function_valued_arguments']


def test_original_impact_graph_render_shares_nodes_and_preserves_obligations():
    from relation_search.oracle_evidence import _render_obligations
    span = dict(path='original.py',start_byte=0,end_byte=4)
    node = dict(span,id=7,kind='read',text='read')
    first = dict(observation_id='first',edit_index=0,path=[node],edge_kinds=[],
                 actual_span=span,expected_span=span,observed='read',expected='1')
    second = dict(first,observation_id='second',edit_index=1)
    rendered = '\n'.join(_render_obligations([first,second]))
    assert rendered.count('N0 [read]')==1
    assert 'E0 -> O0 via P0' in rendered and 'E1 -> O1 via P0' in rendered
    assert 'first' in rendered and 'second' in rendered
    assert 'ORIGINAL S0=original.py' in rendered


def test_render_groups_dense_call_observation_edges_without_dropping_targets():
    from relation_search.oracle_evidence import render_evidence
    span = dict(path='source.py',start_byte=0,end_byte=1)
    call = dict(id='long-call-id',callee='run',span=span,code='run()',targets=[],actual_formal=[])
    assertions = [dict(id='long-q-'+str(i),span=span,code='assert x == '+str(i)) for i in range(5)]
    evidence = dict(added_import_bindings=[],changes=[],calls=[call],assertions=assertions,controls=[],
                    declarations=[],unknowns=[],edges=[dict(source='C:long-call-id',target='Q:'+q['id'],kind='modified_static_slice_may') for q in assertions])
    rendered = render_evidence(evidence)
    assert 'c0 --modified_static_slice_may--> q0, q1, q2, q3, q4' in rendered
    assert 'CALL c0 run M0:0..1' in rendered
    assert all('OBSERVATION q'+str(i)+' M0:0..1' in rendered for i in range(5))
    assert 'MODIFIED-SOURCE M0=source.py' in rendered


def test_render_callback_and_control_references_point_to_nonfirst_call_alias():
    from relation_search.oracle_evidence import render_evidence
    span = dict(path='source.py',start_byte=0,end_byte=1)
    calls = [dict(id=name,callee=name,span=span,code=name+'()',targets=[],actual_formal=[]) for name in ['first','second']]
    evidence = dict(added_import_bindings=[],changes=[],calls=calls,assertions=[],declarations=[],unknowns=[],edges=[],
        function_valued_arguments=[dict(call_id='second',argument='grow',invocation='unknown')],
        controls=[dict(test_id='source_control',call_id='second')])
    rendered = render_evidence(evidence)
    lines = [line for line in rendered.splitlines() if line.startswith(('FUNCTION ARGUMENT','SOURCE CONTROL'))]
    assert len(lines)==2 and all('"call_id": "c1"' in line for line in lines)
    assert 'CALL c1 second M0:0..1' in rendered


def _repeated_assertion_phases():
    from relation_search.impact_selection import select
    code = '''def read(count): return count
def checkpoint(label): return None
def test_case():
    count = 1
    value = read(count)
    assert value == 1
    value = read(count)
    assert value == 1
'''
    corpus,frontend,candidate = setup('python',code,'count = 1','count = 2')
    path = candidate['edits'][0]['span']['path']
    first_call = code.index('value = read(count)')
    insertion_at = code.index('value = read(count)',first_call+1)
    insertion = 'checkpoint("界")\n    '
    candidate['edits'].append(dict(span=dict(path=path,start_byte=insertion_at,end_byte=insertion_at),
                                   before='',after=insertion))
    ranked = select(corpus,frontend,[candidate],1)
    candidate['impact_evidence'] = ranked['ranking'][0]['evidence']
    original = sorted((q['assertion_span'] for q in frontend['observations'] if q['kind']=='assertion'),
                      key=lambda s:s['start_byte'])
    aliases=[]
    for index,extent in enumerate(original):
        shift = len(insertion.encode()) if extent['start_byte'] >= insertion_at else 0
        changed=dict(extent,start_byte=extent['start_byte']+shift,end_byte=extent['end_byte']+shift)
        aliases.append(dict(alias='A'+str(index),original_span=extent,modified_span=changed))
    return corpus,frontend,candidate,aliases


def test_assertion_interface_aliases_distinguish_identical_text_across_inserted_phases():
    corpus,frontend,candidate,aliases = _repeated_assertion_phases()
    untouched = copy.deepcopy((candidate,aliases))
    evidence = build_evidence(corpus,frontend,candidate,assertion_aliases=aliases)
    observations = sorted(evidence['assertions'],key=lambda q:q['span']['start_byte'])
    assert len(observations)==2 and observations[0]['code']==observations[1]['code']=='assert value == 1'
    assert [q['assertion_alias'] for q in observations]==['A0','A1']
    assert [q['span']['start_byte'] for q in observations]==[a['modified_span']['start_byte'] for a in aliases]
    assert len({q['id'] for q in observations})==2
    obligations = sorted(evidence['original_observation_obligations'],key=lambda q:q['assertion_span']['start_byte'])
    assert [q['assertion_alias'] for q in obligations]==['A0','A1']
    lines = evidence['rendered'].splitlines()
    assert len([line for line in lines if line.startswith('OBSERVATION ') and '[A0]' in line])==1
    assert len([line for line in lines if line.startswith('OBSERVATION ') and '[A1]' in line])==1
    assert any(line.startswith('O0 [A0] ') for line in lines)
    assert any(line.startswith('O1 [A1] ') for line in lines)
    assert evidence['assertion_aliases']==aliases
    assert (candidate,aliases)==untouched


def test_assertion_alias_rejects_swapped_identical_text_and_wrong_character_offsets():
    corpus,frontend,candidate,aliases = _repeated_assertion_phases()
    swapped=copy.deepcopy(aliases)
    swapped[0]['modified_span'],swapped[1]['modified_span']=swapped[1]['modified_span'],swapped[0]['modified_span']
    with pytest.raises(ValueError,match='source edit offsets'):
        build_evidence(corpus,frontend,candidate,assertion_aliases=swapped)
    wrong=copy.deepcopy(aliases)
    wrong[1]['modified_span']['start_byte']-=2
    wrong[1]['modified_span']['end_byte']-=2
    with pytest.raises(ValueError,match='source edit offsets'):
        build_evidence(corpus,frontend,candidate,assertion_aliases=wrong)


def test_unoffered_observation_is_explicit_and_no_alias_default_stays_unchanged():
    corpus,frontend,candidate,aliases = _repeated_assertion_phases()
    plain=build_evidence(corpus,frontend,candidate)
    assert 'assertion_aliases' not in plain
    assert all('assertion_alias' not in q for q in plain['assertions'])
    partial=build_evidence(corpus,frontend,candidate,assertion_aliases=aliases[1:])
    observations=sorted(partial['assertions'],key=lambda q:q['span']['start_byte'])
    assert observations[0]['assertion_alias'] is None
    assert observations[0]['assertion_alias_status']=='not_offered'
    assert observations[1]['assertion_alias']=='A1'
    assert '[not offered for editing]' in partial['rendered']
