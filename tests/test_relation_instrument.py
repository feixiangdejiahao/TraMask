"""Runtime profile materialization and measured-parent expansion checks."""
import ast
import copy
import json
import sys
import types

from anchor_retrieval.syntax import Source
from generic_composition.emitter import emit
from relation_search.frontier import Frontier, canonical_profile
from relation_search.instrument import compose_neighbors, instrument_candidates
from relational_gap.frontend import extract_frontend, to_emitter_corpus


SOURCE = '''def accepts(left, right): return True

def test_pairs():
    left = []
    right = []
    assert accepts(left, right)
'''


def position(code, text, *, last=False):
    start = (code.rindex if last else code.index)(text)
    return {'path': 'test_profile.py', 'start_byte': len(code[:start].encode()),
            'end_byte': len(code[:start + len(text)].encode())}


def prepared(code=SOURCE):
    front = extract_frontend([Source('test_profile.py', code, 'python')])
    corpus = to_emitter_corpus(front)
    test_id = next(iter(corpus['tests']))
    actual = position(code, 'right', last=True)
    before = position(code, 'assert accepts(left, right)')
    roles = [{'name': 'left', 'expression': 'left', 'origin_span': position(code, 'left = []')},
             {'name': 'right', 'expression': 'left', 'control_expression': 'right',
              'origin_span': position(code, 'right = []')}]
    row = {'id': 'merge_candidate', 'base_test_id': test_id, 'source_test_ids': [], 'language': 'python',
           'kind': 'binding_merge', 'edits': [{'span': actual, 'before': 'right', 'after': 'left'}],
           'imports': [], 'runtime_probes': [{'phase': 'before_call', 'insert_before': before, 'roles': roles}]}
    return corpus, row


def run_materialized(corpus, result, tmp_path, monkeypatch):
    for helper in result['helper_files']:
        module = types.ModuleType(helper['path'].removesuffix('.py'))
        exec(helper['code'], module.__dict__)
        monkeypatch.setitem(sys.modules, module.__name__, module)
    monkeypatch.setenv('COMBINATION_REPORT_DIR', str(tmp_path))
    emitted = emit(corpus, result['candidates'])
    assert not emitted['unsupported']
    namespace = {}
    exec(compile(emitted['files']['test_profile.py'], '<instrumented-source>', 'exec'), namespace)
    by_id = {row['candidate_id']: row for row in emitted['obligations']}
    for row in result['candidates']:
        namespace[by_id[row['id']]['test_name']]()
    events = [json.loads(line) for line in (tmp_path/'relation_trace.jsonl').read_text().splitlines()]
    return emitted, events


def test_source_and_mutated_profiles_share_roles_cut_and_probe_but_measure_different_aliases(tmp_path, monkeypatch):
    corpus, row = prepared()
    frozen = copy.deepcopy((corpus, row))
    result = instrument_candidates(corpus, [row])
    assert len(result['candidates']) == 2
    baseline, generated = result['candidates']
    assert baseline['is_source_profile'] and not baseline['program_edits']
    assert generated['program_edits'] == row['edits']
    emitted, events = run_materialized(corpus, result, tmp_path, monkeypatch)
    assert len(emitted['controls']) == 1  # Original control stays its own clone.
    assert len(events) == 2
    source, edited = events
    assert source['candidate_id'] == baseline['id']
    assert source['source_window'] == edited['source_window']
    assert source['probe_id'] == edited['probe_id']
    assert source['alias_partition'] == [['left'], ['right']]
    assert edited['alias_partition'] == [['left', 'right']]
    assert canonical_profile(source) != canonical_profile(edited)
    assert (corpus, row) == frozen


def test_candidate_id_and_mutated_expression_do_not_create_new_window_or_seed_clone():
    corpus, row = prepared()
    another = copy.deepcopy(row)
    another['id'] = 'completely_different_candidate_id'
    another['runtime_probes'][0]['roles'][1]['expression'] = 'right'
    result = instrument_candidates(corpus, [row, another])
    assert sum(bool(item.get('is_source_profile')) for item in result['candidates']) == 1
    generated = [item for item in result['candidates'] if not item.get('is_source_profile')]
    assert generated[0]['runtime_probes'][0]['source_window'] == generated[1]['runtime_probes'][0]['source_window']
    assert generated[0]['runtime_probes'][0]['probe_id'] == generated[1]['runtime_probes'][0]['probe_id']
    assert generated[0]['source_profile_ids'] == generated[1]['source_profile_ids']


def test_exact_replacement_boundary_prefixes_probe_without_losing_input_edit(tmp_path, monkeypatch):
    corpus, row = prepared()
    span = position(SOURCE, 'assert accepts(left, right)')
    row['edits'] = [{'span': span, 'before': 'assert accepts(left, right)',
                     'after': 'assert accepts(left, left)', 'role': 'whole_statement_mutation'}]
    result = instrument_candidates(corpus, [row])
    generated = next(item for item in result['candidates'] if not item.get('is_source_profile'))
    assert len(generated['edits']) == 1
    assert generated['edits'][0]['after'].endswith('assert accepts(left, left)')
    assert generated['edits'][0]['instrumented_prefix'] is True
    run_materialized(corpus, result, tmp_path, monkeypatch)


def test_internal_probe_position_is_unsupported_and_original_hypothesis_survives():
    corpus, row = prepared()
    span = position(SOURCE, 'left = []\n    right = []')
    row['edits'] = [{'span': span, 'before': 'left = []\n    right = []',
                     'after': 'left = []\n    right = left'}]
    row['runtime_probes'][0]['insert_before'] = position(SOURCE, 'right = []')
    result = instrument_candidates(corpus, [row])
    original = next(item for item in result['candidates'] if item['id'] == row['id'])
    assert original['edits'] == row['edits']
    assert 'instrumentation' not in original
    record = next(item for item in result['metadata']['records'] if item['candidate_id'] == row['id'])
    assert record['status'] == 'unsupported_probe'
    assert record['reason'] == 'probe_inside_replaced_source_span'


def test_two_probes_at_same_source_cut_form_one_emitter_insertion(tmp_path, monkeypatch):
    corpus, row = prepared()
    row['runtime_probes'].append(copy.deepcopy(row['runtime_probes'][0]))
    row['runtime_probes'][1]['roles'] = [{'name': 'only_left', 'expression': 'left'}]
    result = instrument_candidates(corpus, [row])
    generated = next(item for item in result['candidates'] if not item.get('is_source_profile'))
    inserts = [edit for edit in generated['edits'] if edit['span']['start_byte'] == edit['span']['end_byte']]
    assert len(inserts) == 1
    _, events = run_materialized(corpus, result, tmp_path, monkeypatch)
    assert len(events) == 4


def test_explicit_control_probes_override_mutation_and_instrumentation_is_idempotent():
    corpus, row = prepared()
    row['control_runtime_probes'] = copy.deepcopy(row['runtime_probes'])
    row['control_runtime_probes'][0]['roles'][1]['expression'] = 'right'
    row['runtime_probes'][0]['roles'][1].pop('control_expression')
    once = instrument_candidates(corpus, [row])
    twice = instrument_candidates(corpus, once['candidates'])
    assert once['candidates'] == twice['candidates']
    assert once['helper_files'] == twice['helper_files']


def test_unsupported_calls_are_not_evaluated_or_used_to_drop_candidates():
    corpus, row = prepared()
    row['runtime_probes'][0]['roles'][0]['expression'] = 'dangerous()'
    result = instrument_candidates(corpus, [row])
    assert result['helper_files'] == []
    assert next(item for item in result['candidates'] if item['id'] == row['id'])['edits'] == row['edits']
    assert all(item['status'] == 'unsupported_probe' for item in result['metadata']['records'])


def test_no_probes_or_other_language_is_a_passthrough():
    corpus, row = prepared()
    row.pop('runtime_probes')
    result = instrument_candidates(corpus, [row])
    assert result['candidates'] == [row] and result['helper_files'] == []
    assert instrument_candidates({'language': 'go'}, [row])['candidates'] == [row]


def _edit(start, before, after, role='input'):
    return {'span': {'path': 'test_values.py', 'start_byte': start, 'end_byte': start + len(before)},
            'before': before, 'after': after, 'role': role}


def _row(identifier, edits, base='base_test'):
    return {'id': identifier, 'base_test_id': base, 'source_test_ids': [], 'kind': 'toy_input',
            'language': 'python', 'edits': edits, 'imports': []}


def retained(row):
    return {**copy.deepcopy(row), 'runtime_feedback': {'candidate_id': row['id'],
            'status': 'runtime_observed', 'retained': True, 'measured_profiles': ['actual_profile_hash']}}


def test_composition_requires_actual_retention_and_same_base_nonoverlapping_edits():
    first = _row('first', [_edit(10, '1', '2')])
    second = _row('second', [_edit(20, '2', '3')])
    other = _row('other', [_edit(30, '3', '4')], 'different_test')
    assert compose_neighbors([first], [second, other]) == []
    failed = retained(first)
    failed['runtime_feedback']['status'] = 'no_runtime_profile'
    assert compose_neighbors([failed], [second]) == []
    combined = compose_neighbors([retained(first)], [first, second, other])
    assert len(combined) == 1
    result = combined[0]
    assert result['edits'] == [*first['edits'], *second['edits']]
    assert result['parent_candidate_ids'] == ['first', 'second']
    assert result['provenance']['composition']['runtime_parent_feedback']['measured_profiles']
    assert result['oracle']['applicability'] == 'unknown_requires_fresh_admission'
    assert 'runtime_feedback' not in result


def test_composition_does_not_use_logger_or_semantic_expected_edits():
    first = _row('first', [_edit(10, '1', '2'), _edit(40, '0', '9', 'semantic_expected')])
    first['program_edits'] = copy.deepcopy(first['edits'])
    first['edits'].append(_edit(0, '', 'logger()', 'relation_runtime_probe'))
    second = _row('second', [_edit(20, '2', '3')])
    combined = compose_neighbors([retained(first)], [second])[0]
    assert [edit['role'] for edit in combined['edits']] == ['input', 'input']
    assert combined['program_edits'] == combined['edits']


def test_overlap_already_constructed_and_edit_budget_prune_composition():
    first = _row('first', [_edit(10, 'abc', 'def')])
    overlap = _row('overlap', [_edit(11, 'bc', 'yy')])
    insertion = _row('insertion', [_edit(10, '', 'prefix')])
    second = _row('second', [_edit(20, 'x', 'y')])
    existing = _row('existing', [*first['edits'], *second['edits']])
    assert compose_neighbors([retained(first)], [overlap, insertion]) == []
    assert compose_neighbors([retained(first)], [second], max_edits=1) == []
    assert compose_neighbors([retained(first)], [second, existing]) == []
    assert compose_neighbors([retained(first)], [second], budget=0) == []


def test_composition_accepts_feedback_wrapper_and_rotates_measured_parents():
    first = _row('first', [_edit(10, 'a', 'b')])
    second = _row('second', [_edit(20, 'c', 'd')])
    third = _row('third', [_edit(30, 'e', 'f')])
    fourth = _row('fourth', [_edit(40, 'g', 'h')])
    feedback = retained(first)['runtime_feedback']
    rows = compose_neighbors([{'candidate': first, 'feedback': feedback}, retained(second)], [third, fourth], budget=2)
    assert [row['runtime_parent_id'] for row in rows] == ['first', 'second']
    assert rows == compose_neighbors([{'candidate': first, 'feedback': feedback}, retained(second)], [third, fourth], budget=2)


def test_composed_actual_projections_follow_both_edits_instead_of_reusing_old_alias_assumption():
    first = _row('first', [_edit(10, 'a', 'b')])
    second = _row('second', [_edit(20, 'b', 'c')])
    cut = {'path': 'test_values.py', 'start_byte': 5, 'end_byte': 30}
    original = {'phase': 'before_call', 'insert_before': cut, 'roles': [
        {'name': 'slot0', 'expression': 'a', 'input_span': first['edits'][0]['span']},
        {'name': 'slot1', 'expression': 'b', 'input_span': second['edits'][0]['span']}]}
    for row in (first, second):
        row['runtime_probes'] = [copy.deepcopy(original)]
        row['control_runtime_probes'] = [copy.deepcopy(original)]
    first['runtime_probes'][0]['roles'][0]['expression'] = 'b'
    second['runtime_probes'][0]['roles'][1]['expression'] = 'c'
    combined = compose_neighbors([retained(first)], [second])[0]
    assert len(combined['runtime_probes']) == 1
    assert [r['expression'] for r in combined['runtime_probes'][0]['roles']] == ['b', 'c']
    assert [r['expression'] for r in combined['control_runtime_probes'][0]['roles']] == ['a', 'b']


def test_unlocated_affected_input_projection_is_reported_without_removing_combination():
    first = _row('first', [_edit(10, 'a', 'b')])
    second = _row('second', [_edit(20, 'b', 'c')])
    cut = {'path': 'test_values.py', 'start_byte': 5, 'end_byte': 30}
    first['runtime_probes'] = [{'phase': 'before_call', 'insert_before': cut, 'roles': [
        {'name': 'slot0', 'expression': 'b', 'control_expression': 'a'},
        {'name': 'slot1', 'expression': 'b', 'origin_span': {'path': 'test_values.py', 'start_byte': 0, 'end_byte': 4}}]}]
    combined = compose_neighbors([retained(first)], [second])[0]
    assert len(combined['edits']) == 2
    assert [r['name'] for r in combined['runtime_probes'][0]['roles']] == ['slot0']
    skipped = combined['provenance']['composition']['unavailable_probe_roles']
    assert skipped[0]['reason'] == 'composed_input_projection_missing_actual_span'


def test_composed_subexpression_input_projection_uses_original_source_offsets():
    first = _row('first', [_edit(50, '1', '2')])
    second = _row('second', [_edit(13, '2', '3')])
    first['runtime_probes'] = [{'phase': 'before_call',
        'insert_before': {'path': 'test_values.py', 'start_byte': 5, 'end_byte': 30},
        'roles': [{'name': 'literal_record', 'expression': '[1,2]',
                   'input_span': {'path': 'test_values.py', 'start_byte': 10, 'end_byte': 15}}]}]
    combined = compose_neighbors([retained(first)], [second])[0]
    assert combined['runtime_probes'][0]['roles'][0]['expression'] == '[1,3]'


def test_measured_alias_progress_enables_second_presence_edit_and_measures_new_shape(tmp_path, monkeypatch):
    code = '''def accepts(a, b, options): return True
def test_pairs():
    a = []
    b = []
    options = {"x": 1, "y": 2}
    assert accepts(a, b, options)
'''
    frontend = extract_frontend([Source('test_profile.py', code, 'python')])
    corpus = to_emitter_corpus(frontend)
    test_id = next(iter(corpus['tests']))
    slot_a = position(code, 'a, b, options', last=True)
    slot_a['end_byte'] = slot_a['start_byte'] + 1
    slot_b = position(code, 'b, options', last=True)
    slot_b['end_byte'] = slot_b['start_byte'] + 1
    baseline_roles = [
        {'name': 'first', 'expression': 'a', 'input_span': slot_a, 'origin_span': position(code, 'a = []')},
        {'name': 'second', 'expression': 'b', 'input_span': slot_b, 'origin_span': position(code, 'b = []')},
        {'name': 'options', 'expression': 'options', 'origin_span': position(code, 'options = {"x": 1, "y": 2}')},
    ]
    original_probe = {'phase': 'before_call', 'insert_before': position(code, 'assert accepts(a, b, options)'),
                      'roles': baseline_roles}
    parent = {'id': 'alias_step', 'base_test_id': test_id, 'source_test_ids': [], 'language': 'python',
              'kind': 'alias', 'edits': [{'span': slot_b, 'before': 'b', 'after': 'a'}], 'imports': [],
              'runtime_probes': [copy.deepcopy(original_probe)],
              'control_runtime_probes': [copy.deepcopy(original_probe)]}
    parent['runtime_probes'][0]['roles'][1]['expression'] = 'a'
    first = instrument_candidates(corpus, [parent])
    _, events = run_materialized(corpus, first, tmp_path/'first', monkeypatch)
    frontier = Frontier()
    profile_id = next(row['id'] for row in first['candidates'] if row.get('is_source_profile'))
    frontier.observe(profile_id, [event for event in events if event['candidate_id'] == profile_id])
    feedback = frontier.observe(parent['id'], [event for event in events if event['candidate_id'] == parent['id']])
    assert feedback['retained'] and feedback['new_profiles']
    donor = {'id': 'presence_step', 'base_test_id': test_id, 'source_test_ids': [], 'language': 'python',
             'kind': 'presence', 'edits': [{'span': position(code, '{"x": 1, "y": 2}'),
                                           'before': '{"x": 1, "y": 2}', 'after': '{"x": 1}'}], 'imports': []}
    combined = compose_neighbors([{'candidate': parent, 'feedback': feedback}], [donor])
    assert len(combined) == 1
    second = instrument_candidates(corpus, combined)
    _, events = run_materialized(corpus, second, tmp_path/'second', monkeypatch)
    feedback2 = frontier.observe(combined[0]['id'], [event for event in events if event['candidate_id'] == combined[0]['id']])
    assert feedback2['retained'] and feedback2['new_profiles']
    assert any(('options', ['x'], False) in profile['presence'] for profile in feedback2['new_profiles'])
