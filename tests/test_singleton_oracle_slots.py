import ast
from copy import deepcopy
import json

import pytest

from prototypes.singleton_oracle_slots import (SYSTEM, adapt_frozen_singleton,
    adapt_response, assertion_inventory, contract_without_wrapper, eligible_candidates,
    expected_slot, prepare_requests_v2, render_expected, sha, source_contexts, changed_call_context)
from test_relation_oracle import setup
from anchor_retrieval.syntax import Source
from relational_gap.frontend import extract_frontend, to_emitter_corpus


def frozen(language, assertions):
    if language == 'python':
        head, tail, prelude = 'def test_case():\n', '\n', ''
        body = '\n'.join('    '+code.replace('\n', '\n    ') for code, _ in assertions)
    elif language == 'go':
        head, tail, prelude = 'func TestCase(t *testing.T) {\n', '\n}', 'package sample\n'
        body = '\n'.join(code for code, _ in assertions)
    else:
        head, tail, prelude = "test('case', () => {\n", '\n});', ''
        body = '\n'.join(code for code, _ in assertions)
    full = prelude+head+body+tail
    path = {'python': 'test_case.py', 'go': 'case_test.go', 'typescript': 'case.test.ts'}[language]
    test_span = dict(path=path, start_byte=len(prelude.encode()), end_byte=len(full.encode()))
    corpus = dict(language=language, sources={path: {'code': full}},
                  tests={'source': {'id': 'source', 'span': test_span}})
    candidate = dict(id='fixed_candidate', base_test_id='source', edits=[], imports=[], source_test_ids=[])
    holes, observations = {}, []
    cursor = 0
    for i, (code, observed) in enumerate(assertions):
        actual_code = code.replace('\n', '\n    ') if language == 'python' else code
        at = full.encode().index(actual_code.encode(), cursor)
        extent = dict(path=path, start_byte=at, end_byte=at+len(actual_code.encode()))
        hole = dict(code=actual_code, observed=observed, span=extent)
        holes[f'A{i}'] = hole
        observations.append(dict(test_id='source', kind='assertion', assertion_span=extent,
                                 span=extent, observed={'text': observed}))
        cursor = extent['end_byte']
    offered = {'C0': {'candidate': candidate, 'assertions': holes}}
    original = dict(id='frozen_parent', offered=offered, candidate_source_hash=sha(json.dumps(offered, sort_keys=True)))
    return original, corpus, {'observations': observations}


def adapted(language, assertions, issue='Use the documented behavior.'):
    original, corpus, frontend = frozen(language, assertions)
    result = adapt_frozen_singleton(original, corpus, frontend, issue)
    return result, original, corpus, frontend


def test_input_overlapping_assertion_stays_readonly_when_adapting_other_assertion():
    original, corpus, frontend = frozen('python', [
        ('assert compute(1) == 1', 'compute(1)'), ('assert other == 2', 'other')])
    candidate = original['offered']['C0']['candidate']
    code = corpus['sources']['test_case.py']['code']
    start = code.index('compute(1)') + len('compute(')
    candidate['edits'] = [dict(span=dict(path='test_case.py', start_byte=start, end_byte=start+1),
                                before='1', after='2', role='input')]
    prepared = prepare_requests_v2(corpus, frontend, [candidate], 'The first input changes.')
    request = prepared['requests'][0]
    assert set(request['slots']) == {'A1'}
    assert json.loads(request['prompt'])['readonly_assertions'][0]['id'] == 'A0'
    preserved = adapt_response(request, {'decisions':[dict(id='A1', status='preserve')]}, corpus)
    assert preserved['status'] == 'preserve'
    adapted = adapt_response(request, {'decisions':[dict(id='A1', status='adapt', expected='3')]}, corpus)
    assert adapted['status'] == 'adapt'
    assert len(adapted['revisions']) == 1
    rejected = adapt_response(request, {'decisions':[
        dict(id='A0',status='preserve'),dict(id='A1',status='preserve')]}, corpus)
    assert rejected['status'] == 'unknown'


@pytest.mark.parametrize('code,observed,expected,comparison', [
    ('assert result == 1, report(result)', 'result', '[1, 2]', '!='),
    ('assert 1 == result, report(result)', 'result', '{"items": [1, 2]}', '=='),
    ('assert obj.code == 0, obj.output', 'obj.code', '0', '!='),
])
def test_python_expected_and_operator_preserve_actual_and_diagnostic(code, observed, expected, comparison):
    result, original, corpus, _ = adapted('python', [(code, observed)])
    response = adapt_response(result['request'], {'decisions': [dict(
        id='A0', status='adapt', expected=expected, comparison=comparison)]}, corpus)
    assert response['status'] == 'adapt', response
    assert response['oracle_validity'] == 'unconfirmed'
    edit = response['revisions'][0]['edits'][-1]
    before, after = ast.parse(code).body[0], ast.parse(edit['after']).body[0]
    assert ast.dump(before.msg) == ast.dump(after.msg)
    assert original['offered']['C0']['candidate']['edits'] == []


def test_go_inner_scalar_literal_keeps_wrapper_call_failure_body_and_operator():
    code = 'if got != int64(103) { t.Errorf("got %d", got) }'
    result, _, corpus, _ = adapted('go', [(code, 'got')])
    slot = result['request']['slots']['A0']
    assert slot['expected'] == '103' and slot['retained_wrapper'] == 'int64(103)'
    response = adapt_response(result['request'], {'decisions': [dict(
        id='A0', status='adapt', expected='5004')]}, corpus)
    assert response['status'] == 'adapt', response
    assert response['revisions'][0]['edits'][-1]['after'] == code.replace('103', '5004')
    for invalid in [dict(expected='int64(5004)'), dict(expected='5004', comparison='==')]:
        rejected = adapt_response(result['request'], {'decisions': [dict(id='A0', status='adapt', **invalid)]}, corpus)
        assert rejected['status'] == 'unknown'
        assert rejected['revisions'] == []


def test_expected_value_and_comparison_are_jointly_editable_and_executable():
    result, _, corpus, _ = adapted('python', [('assert value is None, value', 'value')])
    request = result['request']
    assert '==' in request['slots']['A0']['allowed_comparisons']
    response = adapt_response(request, {'decisions': [dict(
        id='A0', status='adapt', expected='300', comparison='==')]}, corpus)
    assert response['status'] == 'adapt'
    code = response['revisions'][0]['edits'][-1]['after']
    exec(code, {'value': int('300')})
    with pytest.raises(AssertionError):
        exec(code, {'value': 301})
    # Preserving the identity operator would turn a value inference into an
    # unsupported assertion about object interning.
    invalid = adapt_response(request, {'decisions': [dict(
        id='A0', status='adapt', expected='300')]}, corpus)
    assert invalid['status'] == 'unknown' and invalid['revisions'] == []


def test_typescript_container_can_change_without_changing_matcher_or_actual():
    code = 'expect(actual).toEqual({items: [1], tag: "old"});'
    result, _, corpus, _ = adapted('typescript', [(code, 'actual')])
    response = adapt_response(result['request'], {'decisions': [dict(
        id='A0', status='adapt', expected='{items: [1, 2], tag: "new"}')]}, corpus)
    assert response['status'] == 'adapt', response
    changed = response['revisions'][0]['edits'][-1]['after']
    assert changed == 'expect(actual).toEqual({items: [1, 2], tag: "new"});'


def test_existing_helper_is_background_and_zero_slots_do_not_dispatch():
    original, corpus, frontend = frozen('go', [('verify(t, object, "old")', 'verify(t, object, "old")')])
    result = adapt_frozen_singleton(original, corpus, frontend, 'The helper is not supported.')
    assert result['request'] is None
    assert result['record']['status'] == 'unknown_no_editable_slot'
    assert result['model_calls'] == 0


def test_all_related_assertions_are_joint_and_unsupported_forms_stay_background():
    result, _, corpus, _ = adapted('python', [
        ('assert result == 1', 'result'), ('assert result is not None', 'result'),
        ('assert bool(result)', 'bool(result)')])
    request = result['request']
    wire = json.loads(request['prompt'])
    assert [row['id'] for row in wire['editable_assertions']] == ['A0', 'A1']
    assert [row['id'] for row in wire['readonly_assertions']] == ['A2']
    assert 'assert bool(result)' in wire['modified_test']
    partial = {'decisions': [{'id': 'A0', 'status': 'adapt', 'expected': '2'}]}
    assert adapt_response(request, partial, corpus)['reason'] == 'missing_joint_assertion_decisions'
    partial['decisions'].append({'id': 'A1', 'status': 'unknown'})
    uncertain = adapt_response(request, partial, corpus)
    assert uncertain['status'] == 'unknown' and uncertain['revisions'] == []
    partial['decisions'][-1]['status'] = 'preserve'
    assert adapt_response(request, partial, corpus)['status'] == 'adapt'


def test_preserve_unknown_and_empty_output_are_distinct_unconfirmed_judgments():
    result, _, corpus, _ = adapted('python', [('assert result == 1', 'result')])
    request = result['request']
    preserved = adapt_response(request, {'decisions': [{'id': 'A0', 'status': 'preserve'}]}, corpus)
    assert preserved['status'] == 'preserve' and preserved['revisions'] == []
    assert preserved['oracle_validity'] == 'unconfirmed'
    assert adapt_response(request, {'status': 'unknown'}, corpus)['reason'] == 'model_uncertain'
    assert adapt_response(request, {'decisions': []}, corpus)['reason'] == 'missing_joint_assertion_decisions'
    assert adapt_response(request, {}, corpus)['status'] == 'unknown'


@pytest.mark.parametrize('decision', [
    {'id': 'A0', 'status': 'adapt', 'expected': 'result'},
    {'id': 'A0', 'status': 'adapt', 'expected': 'clear_inputs()'},
    {'id': 'A0', 'status': 'adapt', 'expected': '2\nassert False'},
    {'id': 'A0', 'status': 'adapt', 'expected': '2', 'comparison': 'in'},
    {'id': 'A0', 'status': 'adapt', 'code': 'assert False'},
    {'id': 'A0', 'status': 'preserve', 'expected': '2'},
    {'id': 'invented', 'status': 'adapt', 'expected': '2'},
])
def test_unoffered_edits_calls_and_extra_code_are_rejected(decision):
    result, _, corpus, _ = adapted('python', [('assert result == 1', 'result')])
    outcome = adapt_response(result['request'], {'decisions': [decision]}, corpus)
    assert outcome['status'] == 'unknown' and outcome['revisions'] == []


def test_large_contract_and_all_observations_survive_or_entire_request_is_skipped():
    specification = 'specification ' * 2000 + '\nFINAL IMPORTANT REQUIREMENT'
    assertions = [(f'assert values[{i}] == {i}', f'values[{i}]') for i in range(64)]
    original, corpus, frontend = frozen('python', assertions)
    large = adapt_frozen_singleton(original, corpus, frontend, specification, max_bytes=100000)
    wire = json.loads(large['request']['prompt'])
    assert wire['issue_contract'] == specification
    assert len(wire['editable_assertions']) == 64
    small = adapt_frozen_singleton(original, corpus, frontend, specification, max_bytes=2000)
    assert small['request'] is None and small['record']['status'] == 'unknown_context_budget'
    assert small['record']['truncated'] is False


def test_wrapper_removal_preserves_subject_instructions_and_long_specification():
    subject = 'Important requirement.\n' * 1500
    issue = subject + '\n## Recommended Workflow\nRun shell.\n## Command Execution Rules\nOther.'
    assert contract_without_wrapper(issue) == subject.strip()
    ordinary = 'Explain the text ## Recommended Workflow in the document.'
    assert contract_without_wrapper(ordinary) == ordinary


def test_no_slot_candidate_does_not_consume_request_budget_or_disappear_from_records():
    corpus, frontend, candidate = setup()
    no_slot = deepcopy(candidate)
    no_slot['id'] = 'covered_assertion'
    hole = assertion_inventory(corpus, frontend, candidate)[0]
    no_slot['edits'].append(dict(span=hole['span'], before=hole['code'], after='assert result > 0'))
    result = prepare_requests_v2(corpus, frontend, [no_slot, candidate], 'Count values.', max_requests=1)
    assert len(result['requests']) == 1
    assert len(result['records']) == 2
    assert result['records'][0]['status'] == 'unknown_no_editable_slot'
    assert result['requests'][0]['offered']['C0']['candidate']['id'] == candidate['id']
    qualified = eligible_candidates(corpus, frontend, [no_slot, candidate])
    assert qualified['candidates'] == [candidate]


def test_request_singletons_never_merge_two_candidates_and_keep_source_inputs():
    corpus, frontend, first = setup()
    second = deepcopy(first)
    second['id'] = 'another_candidate'
    second['edits'][0]['after'] = '[1, 2, 3]'
    result = prepare_requests_v2(corpus, frontend, [first, second], 'Count values.')
    assert len(result['requests']) == 2
    for request, candidate in zip(result['requests'], [first, second]):
        assert len(request['offered']) == 1
        assert request['offered']['C0']['candidate'] == candidate
        wire = json.loads(request['prompt'])
        assert candidate['edits'][0]['after'] in wire['modified_test']
        assert wire['input_changes'][0]['before'] == '[1]'


def test_resolved_helper_declaration_is_whole_and_unresolved_dependencies_explicit():
    test = Source('test_items.py', '''from helper import count
def test_count():
    values = [1]
    result = count(values)
    assert result == 1
''', 'python')
    helper = Source('helper.py', '''def count(values):
    state = values
    return external_count(state)
''', 'python')
    frontend = extract_frontend([test, helper])
    corpus = to_emitter_corpus(frontend)
    test_id = next(identifier for identifier, item in corpus['tests'].items() if item['name'] == 'test_count')
    at = test.code.index('[1]')
    candidate = dict(id='new_input', base_test_id=test_id, edits=[dict(
        span={'path':test.path, 'start_byte':at, 'end_byte':at+3}, before='[1]', after='[1, 2]')],
        imports=[], source_test_ids=[])
    result = prepare_requests_v2(corpus, frontend, [candidate], 'Count all values.')
    wire = json.loads(result['requests'][0]['prompt'])
    assert any(row['code'] == helper.code.strip() for row in wire['source_context']['declarations'])
    assert any(row.get('callee') == 'external_count' for row in wire['source_context']['missing'])
    assert 'state = values' in json.dumps(wire)


@pytest.mark.parametrize('before,after,new_callee',[
    ('original','alternate','alternate'),
    ('original(1)','alternate(original(1))','alternate'),
])
def test_changed_or_new_callee_does_not_inherit_original_resolution(before,after,new_callee):
    source = Source('test_calls.py', '''from helpers import original, alternate
def test_call():
    result = original(1)
    assert result == 1
''','python')
    helpers = Source('helpers.py','def original(x): return x\ndef alternate(x): return x + 1\n','python')
    frontend = extract_frontend([source,helpers])
    corpus = to_emitter_corpus(frontend)
    test_id = next(iter(corpus['tests']))
    start = source.code.index('original(1)')
    candidate = dict(id='syntax_change',base_test_id=test_id,edits=[dict(
        span=dict(path=source.path,start_byte=start,end_byte=start+len(before)),before=before,after=after)],
        imports=[],source_test_ids=[])
    context = source_contexts(corpus,frontend,candidate)
    invalidated,_ = changed_call_context(corpus,candidate)
    old_call = next(row for row in frontend['calls'] if row['callee']=='original')['span']
    assert (old_call['path'],old_call['start_byte'],old_call['end_byte']) in invalidated
    assert any(row.get('callee') == new_callee and row['reason']=='new_callee_unresolved'
               for row in context['missing'])
    assert any(row['reason']=='edited_callee_unresolved' for row in context['missing'])
    assert not any(row['role']=='candidate_declaration_not_oracle' and 'def original(' in row['code']
                   for row in context['declarations'])
    assert not any(row['role']=='candidate_declaration_not_oracle' and 'def alternate(' in row['code']
                   for row in context['declarations'])


def test_changed_method_receiver_is_unresolved_without_guessing_receiver_type():
    original,corpus,frontend = frozen('python',[('assert first.step(1) == 1','first.step(1)')])
    candidate=original['offered']['C0']['candidate']
    code=corpus['sources']['test_case.py']['code']
    start=code.index('first.step')
    candidate['edits']=[dict(span=dict(path='test_case.py',start_byte=start,end_byte=start+5),
                             before='first',after='second')]
    context=source_contexts(corpus,frontend,candidate)
    assert any(row.get('callee')=='second.step' and row['reason']=='new_callee_unresolved'
               for row in context['missing'])
    assert any(row.get('original_callee')=='first.step' for row in context['missing'])


def test_argument_only_edit_keeps_existing_callee_context():
    source=Source('test_calls.py','from helper import original\ndef test_call():\n    result = original(1)\n    assert result == 1\n','python')
    helper=Source('helper.py','def original(x): return x\n','python')
    frontend=extract_frontend([source,helper]);corpus=to_emitter_corpus(frontend)
    start=source.code.index('original(1)')+len('original(')
    candidate=dict(id='arg_change',base_test_id=next(iter(corpus['tests'])),edits=[dict(
        span=dict(path=source.path,start_byte=start,end_byte=start+1),before='1',after='2')],imports=[],source_test_ids=[])
    context=source_contexts(corpus,frontend,candidate)
    assert not context['missing']
    assert any(row['code']==helper.code.strip() for row in context['declarations'])
    assert changed_call_context(corpus,candidate)[0] == set()


def test_paired_adapter_keeps_provider_parameters_and_freezes_source_identity():
    original, corpus, frontend = frozen('python', [('assert result == 1', 'result')])
    original['thinking'], original['reasoning_effort'] = 'disabled', 'low'
    result = adapt_frozen_singleton(original, corpus, frontend, 'Subject behavior.')
    request = result['request']
    assert request['thinking'] == 'disabled' and request['reasoning_effort'] == 'low'
    changed = deepcopy(corpus)
    next(iter(changed['sources'].values()))['code'] += '\n# changed source\n'
    assert adapt_response(request, {'status':'unknown'}, changed)['reason'] == 'source_snapshot_changed'
    altered = deepcopy(original)
    altered['offered']['C0']['assertions']['A0']['code'] = 'assert result == 9'
    altered['candidate_source_hash'] = sha(json.dumps(altered['offered'],sort_keys=True))
    assert adapt_frozen_singleton(altered,corpus,frontend,'behavior')['record']['status'] == 'unknown_observer_source_changed'


def test_adapt_does_not_create_a_revision_from_spacing_changes_only():
    result, _, corpus, _ = adapted('python', [('assert result==1', 'result')])
    response = adapt_response(result['request'], {'decisions':[dict(id='A0',status='adapt',expected='1')]}, corpus)
    assert response['reason'] == 'adapt_does_not_change_assertion'
