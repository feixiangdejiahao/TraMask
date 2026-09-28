"""Independent three-version strings and opaque record carriers."""
import ast
import json

import pytest

from anchor_retrieval.syntax import Source
from generic_composition.emitter import emit
from relational_gap.frontend import extract_frontend, to_emitter_corpus
from relational_gap.sequence_cells import SequenceBudget, allen_relation, generate_sequence_cells, line_edit


BASE = 'alpha\nbeta\ngamma\ndelta\nepsilon\n'
LEFT = 'alpha\nLEFT\ngamma\ndelta\nepsilon\n'
RIGHT = 'alpha\nbeta\ngamma\nRIGHT\nepsilon\n'


def corpus_for(code, language='python'):
    path = {'python': 'test_versions.py', 'typescript': 'versions.test.ts', 'go': 'versions_test.go'}[language]
    frontend = extract_frontend([Source(path, code, language)])
    return to_emitter_corpus(frontend), frontend


def direct_source(base=BASE, left=LEFT, right=RIGHT, name='versions'):
    return f'''seen = []
def accept(first, second, third):
    seen.append((first, second, third))
    return True

def test_{name}():
    assert accept({base!r}, {left!r}, {right!r}) is True
'''


def execute(corpus, candidate):
    output = emit(corpus, [candidate])
    assert not output['unsupported']
    namespace = {}
    for code in output['files'].values():
        exec(compile(code, '<source-sequence-witness>', 'exec'), namespace)
    namespace[output['obligations'][0]['test_name']]()
    return namespace, output


@pytest.mark.parametrize(('left', 'right', 'expected'), [
    ((0, 1), (2, 3), 'before'), ((0, 1), (1, 3), 'meets'),
    ((0, 2), (1, 3), 'overlaps'), ((0, 1), (0, 3), 'starts'),
    ((1, 2), (0, 3), 'during'), ((1, 3), (0, 3), 'finishes'),
    ((0, 3), (0, 3), 'equal'), ((2, 3), (0, 1), 'after'),
    ((1, 3), (0, 1), 'met_by'), ((1, 3), (0, 2), 'overlapped_by'),
    ((0, 3), (0, 1), 'started_by'), ((0, 3), (1, 2), 'contains'),
    ((0, 3), (1, 3), 'finished_by'),
])
def test_directed_half_open_interval_partition(left, right, expected):
    assert allen_relation(left, right) == expected


def test_direct_three_inputs_cover_missing_relations_with_exact_source_fragment_rematches():
    corpus, frontend = corpus_for(direct_source())
    result = generate_sequence_cells(corpus, frontend)
    candidates = result['candidates']
    assert len(candidates) == 12
    assert {row['relation']['cell']['allen_relation'] for row in candidates} == {
        'meets', 'overlaps', 'starts', 'during', 'finishes', 'equal', 'after',
        'met_by', 'overlapped_by', 'started_by', 'contains', 'finished_by'}
    assert all(row['relation']['source_base_index'] == 0 for row in candidates)
    assert all(row['relation']['base_status'] == 'unique_source_single_hunk_base' for row in candidates)
    for candidate in candidates:
        namespace, _ = execute(corpus, candidate)
        base, left, right = namespace['seen'][0]
        assert base == BASE
        actual = [line_edit(base, value) for value in (left, right)]
        assert actual == candidate['provenance']['rematched_edit_footprints']
        assert [edit['replacement'] for edit in actual] == ['LEFT\n', 'RIGHT\n']
        assert allen_relation(*(edit['interval'] for edit in actual)) == candidate['relation']['cell']['allen_relation']
        assert candidate['oracle']['assertion_ids'] == [candidate['source_observation_id']]
        assert all(candidate['provenance']['checks'].values())
    json.dumps(result)


def test_partial_overlap_can_move_both_original_one_line_footprints_with_bounded_search():
    lines = [f'unique-{index}\n' for index in range(24)]
    base = ''.join(lines)
    left = ''.join(lines[:10] + ['LEFT\n'] + lines[11:])
    right = ''.join(lines[:12] + ['RIGHT\n'] + lines[13:])
    corpus, frontend = corpus_for(direct_source(base, left, right))
    result = generate_sequence_cells(corpus, frontend, budget=SequenceBudget(max_pair_plans=256))
    candidate = next(row for row in result['candidates'] if row['relation']['cell']['allen_relation'] == 'overlaps')
    a, b = candidate['relation']['cell']['left_interval']
    c, d = candidate['relation']['cell']['right_interval']
    assert a < c < b < d
    assert candidate['selection']['edit_cost']['changed_version_count'] == 2
    assert len(candidate['edits']) == 2


def test_successive_nested_record_versions_keep_carrier_paths_and_other_values():
    code = f'''records = []
class Recorder:
    def put(self, record): records.append(record)
    def count(self): return len(records)

def test_versions():
    receiver = Recorder()
    receiver.put({{'nested': {{'content': {BASE!r}}}, 'quota': 2}})
    receiver.put({{'nested': {{'content': {LEFT!r}}}, 'quota': 2}})
    receiver.put({{'nested': {{'content': {RIGHT!r}}}, 'quota': 2}})
    assert receiver.count() == 3
'''
    corpus, frontend = corpus_for(code)
    result = generate_sequence_cells(corpus, frontend)
    assert result['candidates'], result['skipped']
    candidate = next(row for row in result['candidates'] if row['relation']['cell']['allen_relation'] == 'overlaps')
    assert candidate['relation']['carrier_kind'] == 'successive_source_versions_at_structural_port'
    expected_path = [{'kind': 'key', 'value': 'nested'}, {'kind': 'key', 'value': 'content'}]
    assert candidate['provenance']['source_structural_paths'] == [expected_path] * 3
    assert candidate['relation']['alignment']['receiver_alignment'][0] == 'source_binding'
    namespace, _ = execute(corpus, candidate)
    assert len(namespace['records']) == 3
    assert all(record['quota'] == 2 for record in namespace['records'])
    base, left, right = [record['nested']['content'] for record in namespace['records']]
    assert base == BASE
    assert allen_relation(line_edit(base, left)['interval'], line_edit(base, right)['interval']) == 'overlaps'


def test_assigned_record_carriers_follow_source_binding_without_replacing_container():
    code = f'''seen = []
def store(record): seen.append(record)

def test_versions():
    first = {{'body': {BASE!r}, 'keep': 7}}
    store(first)
    second = {{'body': {LEFT!r}, 'keep': 7}}
    store(second)
    third = {{'body': {RIGHT!r}, 'keep': 7}}
    store(third)
    assert len(seen) == 3
'''
    corpus, frontend = corpus_for(code)
    candidates = generate_sequence_cells(corpus, frontend)['candidates']
    assert candidates
    namespace, _ = execute(corpus, candidates[0])
    assert all(record['keep'] == 7 for record in namespace['seen'])
    assert all(not edit['before'].startswith('{') for edit in candidates[0]['edits'])


def test_base_is_a_structural_hypothesis_and_is_not_assumed_to_be_argument_zero():
    corpus, frontend = corpus_for(direct_source(LEFT, BASE, RIGHT))
    result = generate_sequence_cells(corpus, frontend)
    assert result['candidates']
    assert {row['relation']['source_base_index'] for row in result['candidates']} == {1}
    assert all(row['relation']['base_role_semantics'] == 'unknown_source_version_hypothesis' for row in result['candidates'])


def test_unicode_and_crlf_payload_byte_coordinates_reference_exact_source_fragment():
    base = '甲\r\n乙\r\n丙\r\n丁\r\n戊\r\n'
    left = base.replace('乙', '左🙂')
    right = base.replace('丁', '右é')
    corpus, frontend = corpus_for(direct_source(base, left, right))
    candidate = generate_sequence_cells(corpus, frontend)['candidates'][0]
    for value, footprint in zip((left, right), candidate['provenance']['source_edit_footprints']):
        lo, hi = footprint['source_version_bytes']
        assert value.encode()[lo:hi].decode() == footprint['replacement']
    namespace, _ = execute(corpus, candidate)
    assert namespace['seen'][0][0] == base
    assert all('\n' not in value.replace('\r\n', '') for value in namespace['seen'][0])


def test_repeated_context_and_multi_hunk_versions_are_explicitly_unsupported():
    base = 'same\nsame\na\nb\nc\nd\n'
    corpus, frontend = corpus_for(direct_source(base, base.replace('b\n', 'LEFT\n'), base.replace('d\n', 'RIGHT\n')))
    result = generate_sequence_cells(corpus, frontend)
    assert not result['candidates']
    assert result['skipped']['base_line_context_not_unique']
    base = 'a\nb\nc\nd\ne\nf\ng\n'
    left = base.replace('b\n', 'LEFT\n').replace('d\n', 'MORE\n')
    right = base.replace('f\n', 'RIGHT\n')
    corpus, frontend = corpus_for(direct_source(base, left, right))
    result = generate_sequence_cells(corpus, frontend)
    assert not result['candidates']
    assert result['skipped']['base_diffs_not_two_single_nonempty_hunks']


def test_pure_insertions_are_not_misrepresented_as_nonempty_allen_footprints():
    corpus, frontend = corpus_for(direct_source(BASE, BASE.replace('beta\n', 'LEFT\nbeta\n'),
                                               BASE.replace('delta\n', 'RIGHT\ndelta\n')))
    assert not generate_sequence_cells(corpus, frontend)['candidates']
    with pytest.raises(ValueError, match='nonempty'):
        allen_relation((1, 1), (2, 3))


def test_different_record_paths_or_receiver_bindings_do_not_form_a_version_triple():
    code = f'''class Recorder:
    def put(self, value): pass

def test_paths():
    receiver = Recorder()
    receiver.put({{'left': {BASE!r}}})
    receiver.put({{'middle': {LEFT!r}}})
    receiver.put({{'right': {RIGHT!r}}})
    assert True

def test_receivers():
    first = Recorder()
    second = Recorder()
    third = Recorder()
    first.put({BASE!r})
    second.put({LEFT!r})
    third.put({RIGHT!r})
    assert True
'''
    corpus, frontend = corpus_for(code)
    assert not generate_sequence_cells(corpus, frontend)['candidates']


def test_snapshot_observer_before_successive_versions_is_not_selected_as_later_q():
    code = f'''seen = []
def store(value): seen.append(value)

def test_versions():
    early = len(seen)
    store({BASE!r})
    store({LEFT!r})
    store({RIGHT!r})
    assert early == 0
'''
    corpus, frontend = corpus_for(code)
    result = generate_sequence_cells(corpus, frontend)
    assert not result['candidates']
    assert result['skipped']['following_source_observation_not_recovered']


def test_attempt_and_parent_budgets_are_explicit_and_deterministic():
    code = direct_source() + ''.join(f'''def test_{name}():
    assert accept({BASE!r}, {LEFT!r}, {RIGHT!r}) is True

''' for name in ['north', 'south'])
    corpus, frontend = corpus_for(code)
    budget = SequenceBudget(max_candidates=3)
    result = generate_sequence_cells(corpus, frontend, budget=budget)
    assert len(result['candidates']) == 3
    assert len({row['base_test_id'] for row in result['candidates']}) == 3
    assert result['budget_exhausted']
    assert result == generate_sequence_cells(corpus, frontend, budget=budget)
    result = generate_sequence_cells(corpus, frontend, budget=SequenceBudget(max_pair_plans=1))
    assert not result['candidates']
    assert result['budget_exhausted'] and result['skipped']['pair_plan_budget']
    result = generate_sequence_cells(corpus, frontend, budget=SequenceBudget(max_attempts=1))
    assert result['attempts'] == 1 and result['budget_exhausted']


@pytest.mark.parametrize('language', ['typescript', 'go'])
def test_language_literals_are_emitted_in_existing_observation_frame(language):
    values = ', '.join(json.dumps(value) for value in (BASE, LEFT, RIGHT))
    if language == 'typescript':
        code = f'''function accept(a: string, b: string, c: string) {{ return true; }}
test('versions', () => {{ expect(accept({values})).toBe(true); }});
'''
    else:
        code = f'''package sample
import "testing"
func accept(a, b, c string) bool {{ return true }}
func TestVersions(t *testing.T) {{
    if !accept({values}) {{ t.Fatal("unexpected") }}
}}
'''
    corpus, frontend = corpus_for(code, language)
    result = generate_sequence_cells(corpus, frontend)
    assert result['candidates'], result['skipped']
    output = emit(corpus, result['candidates'][:2])
    assert not output['unsupported']
    assert all(not Source(path, code, language).root.has_error for path, code in output['files'].items())


@pytest.mark.parametrize('budget', [SequenceBudget(max_candidates=0), SequenceBudget(max_lines=2)])
def test_invalid_budgets_are_rejected(budget):
    corpus, frontend = corpus_for(direct_source())
    with pytest.raises(ValueError, match='Sequence budgets'):
        generate_sequence_cells(corpus, frontend, budget=budget)
