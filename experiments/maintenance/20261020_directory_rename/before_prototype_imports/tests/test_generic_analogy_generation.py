"""Automatic full-test analogies from miniature repositories only."""
import json

from generic_composition.corpus import build_corpus
from generic_composition.emitter import emit
from generic_composition.gate import presentation, selection_candidates
from experimental.generic_v2.generate import Budget, gate_evidence, generate


def corpus(tmp_path, code, language='python', retrieval=None):
    name = {'python': 'test_shapes.py', 'go': 'shapes_test.go', 'typescript': 'shapes.test.ts'}[language]
    (tmp_path / name).write_text(code)
    return build_corpus(tmp_path, language, retrieval)


SHAPES = '''def test_scalar():
    x = f(3)
    assert x == 6
def test_container():
    x = f([3])
    assert x == [6]
def test_other_value():
    y = f(5)
    assert y == 10
'''


def test_automatically_selects_three_sources_and_transports_input_and_oracle(tmp_path):
    data = corpus(tmp_path, SHAPES)
    output = generate(data)
    matches = [p for p in output['candidates'] if p['edits'][0]['after'] == 'y = f([5])\n    assert y == [10]']
    assert matches
    candidate = matches[0]
    assert candidate['oracle']['mode'] == 'transport_from_source'
    assert candidate['oracle']['source_test_id'].endswith(':test_container')
    assert candidate['oracle']['binding_source_test_id'].endswith(':test_other_value')
    assert all(candidate['provenance']['checks'].values())
    assert set(candidate['provenance']['sources']) == {'A', 'B', 'C'}
    assert len(candidate['source_test_ids']) == 2
    json.dumps(output)
    emitted = emit(data, [candidate])
    assert len(emitted['obligations']) == 1 and len(emitted['controls']) == 3
    assert emitted['unsupported'] == []
    assert 'assert y == [10]' in emitted['files']['test_shapes.py']


def test_strong_observer_is_taken_from_existing_B_not_generated_by_a_model(tmp_path):
    data = corpus(tmp_path, '''def test_weak():
    box = make(0)
    box.put(4)
    assert box is not None
def test_observer():
    box = make(0)
    box.put(4)
    assert box.peek() == 4
def test_another_input():
    box = make(0)
    box.put(9)
    assert box is not None
''')
    output = generate(data)
    matches = [p for p in output['candidates'] if 'box.put(9)' in p['edits'][0]['after']
               and 'assert box.peek() == 9' in p['edits'][0]['after']]
    assert matches
    assert matches[0]['oracle']['source_test_id'].endswith(':test_observer')
    assert 'oracle_validity' in matches[0]['provenance']['unproved']


def test_source_derived_ports_disambiguate_equal_input_and_expected_literals(tmp_path):
    data = corpus(tmp_path, '''def test_scalar():
    assert f(1) == 1
def test_container():
    assert f([1]) == [1]
def test_other_value():
    assert f(2) == 7
''')
    output = generate(data)
    assert any(p['edits'][0]['after'] == 'assert f([2]) == [7]' for p in output['candidates'])


def test_retrieved_side_can_supply_context_or_observation(tmp_path):
    for name, line in [('test_container', 4), ('test_other_value', 7)]:
        data = corpus(tmp_path, SHAPES, retrieval={'selected_tests': [
            {'rank': 1, 'path': 'test_shapes.py', 'line': line, 'name': name}]})
        output = generate(data)
        assert any(p['edits'][0]['after'] == 'y = f([5])\n    assert y == [10]'
                   for p in output['candidates'])
        seeds = {tid for tid, test in data['tests'].items() if test['retrieval_rank'] == 1}
        assert all(seeds & {p['base_test_id'], *p['source_test_ids']} for p in output['candidates'])


def test_incompatible_parameter_interface_is_not_mixed(tmp_path):
    data = corpus(tmp_path, SHAPES.replace('def test_other_value():', 'def test_other_value(other_fixture):'))
    output = generate(data)
    assert output['candidates'] == []
    assert output['skipped']['fewer_than_three_tests'] > 0


def test_different_enclosing_class_is_not_assumed_to_share_bindings(tmp_path):
    code = '''class TestFirst:
    def test_scalar(self):
        assert f(3) == 6
    def test_container(self):
        assert f([3]) == [6]
class TestSecond:
    def test_other_value(self):
        assert f(5) == 10
'''
    output = generate(corpus(tmp_path, code))
    assert output['candidates'] == []
    assert output['skipped']['fewer_than_three_tests'] > 0


def test_literal_parameter_rows_are_coupled_full_test_instances(tmp_path):
    code = '''import pytest
@pytest.mark.parametrize("value,want", [(1,1),([1],[1]),(2,7)], ids=["a","b","c"])
def test_table(value,want):
    assert f(value) == want
'''
    data = corpus(tmp_path, code)
    output = generate(data)
    matches = [p for p in output['candidates'] if p['edits'][0]['after'] ==
               'value = [2]\n    want = [7]\n    assert f(value) == want']
    assert matches
    candidate = matches[0]
    assert candidate['edits'][1]['after'] == '[(2,7)]'
    assert candidate['edits'][2]['after'] == '["c"]'
    assert len(candidate['source_test_ids']) == 1
    assert len({v['instance_id'] for v in candidate['provenance']['sources'].values()}) == 3
    assert all('instantiation' in v for v in candidate['provenance']['sources'].values())
    result = emit(data, [candidate])
    assert len(result['obligations']) == 1 and result['unsupported'] == []
    json.dumps(output)


def test_parameter_instantiation_preserves_multiple_uses_of_same_object(tmp_path):
    data = corpus(tmp_path, '''import pytest
@pytest.mark.parametrize("value,want", [(1,1),([1],[1]),(2,7)])
def test_table(value,want):
    result = f(value)
    assert result == want
    assert value is value
''')
    output = generate(data)
    matches = [p for p in output['candidates'] if 'value = [2]' in p['edits'][0]['after']
               and 'want = [7]' in p['edits'][0]['after']]
    assert matches
    assert 'assert value is value' in matches[0]['edits'][0]['after']
    assert matches[0]['edits'][0]['after'].count('value =') == 1


def test_parameter_rebinding_is_an_explicit_structure_limit(tmp_path):
    output = generate(corpus(tmp_path, '''import pytest
@pytest.mark.parametrize("value,want", [(1,1),([1],[1]),(2,7)])
def test_table(value,want):
    value = 4
    assert f(value) == want
'''))
    assert output['candidates'] == []
    assert output['skipped']['parameter_rebinding_unsupported'] == 1


def test_many_same_shape_examples_do_not_hide_wrapper_source(tmp_path):
    code = ''.join(f'def test_scalar_{i:02d}():\n    assert f({i}) == {i * 2}\n' for i in range(1, 21))
    code += 'def test_wrapped():\n    assert f([1]) == [2]\n'
    generated = generate(corpus(tmp_path, code))
    assert any(p['edits'][0]['after'].startswith('assert f([')
               and p['edits'][0]['after'] != 'assert f([1]) == [2]' for p in generated['candidates'])
    assert generated['counts']['attempted_triples'] <= 2000
    assert generated['counts']['candidates'] <= 128


def test_exact_existing_fourth_test_is_not_reported_as_missing(tmp_path):
    code = SHAPES + 'def test_already_combined():\n    y = f([5])\n    assert y == [10]\n'
    output = generate(corpus(tmp_path, code))
    assert not any(p['edits'][0]['after'] == 'y = f([5])\n    assert y == [10]' for p in output['candidates'])
    assert output['skipped']['existing_combination'] > 0


def test_alpha_only_context_is_not_a_new_behavioral_combination(tmp_path):
    output = generate(corpus(tmp_path, '''def test_first():
    x = f(1)
    assert x == 2
def test_renamed():
    y = f(1)
    assert y == 2
def test_other():
    x = f(3)
    assert x == 6
'''))
    assert output['candidates'] == []
    assert output['skipped']['existing_combination'] > 0


def test_gate_receives_concrete_row_sources_outside_candidate_provenance(tmp_path):
    data = corpus(tmp_path, '''import pytest
@pytest.mark.parametrize("value,want", [(1,1),([1],[1]),(2,7)])
def test_table(value,want):
    assert f(value) == want
''')
    generated = generate(data)
    evidence, candidates = gate_evidence(data, generated, 'Collection API contract')
    assert candidates
    for candidate in candidates:
        mappings = evidence['analogy_sources'][candidate['rule_id']]
        assert set(mappings) == {'A', 'B', 'C'}
        sources = {name: evidence['analogy_instances'][uid] for name, uid in mappings.items()}
        assert len({s['parameter_row']['row'] for s in sources.values()}) == 3
        assert all('value =' in s['body'] for s in sources.values())
    shown = presentation(evidence, selection_candidates(candidates, 'ordinal_v1'))
    assert shown['candidates'][0]['id'] == 'c0'
    assert all(p['rule_id'] in shown['evidence']['analogy_sources'] for p in shown['candidates'])


def test_string_tokens_and_row_roles_jointly_transport_repeated_equal_fragments(tmp_path):
    data = corpus(tmp_path, '''import pytest
@pytest.mark.parametrize("value,want", [
    ("call(1)", "out(1)"),
    ("box(call(1))", "box(out(1))"),
    ("call(2)", "out(7)"),
])
def test_table(value,want):
    assert f(value) == want
''')
    generated = generate(data)
    matches = [p for p in generated['candidates'] if
               'value = "box(call(2))"' in p['edits'][0]['after'] and
               'want = "box(out(7))"' in p['edits'][0]['after']]
    assert matches
    assert matches[0]['binding_check']['status'] == 'unknown'
    assert generated['binding_statuses']['unknown'] > 0
    assert matches[0]['binding_check']['unknowns']
    assert emit(data, [matches[0]])['unsupported'] == []


def test_binding_check_filters_known_invalid_arity_before_semantic_gate(tmp_path):
    data = corpus(tmp_path, '''def f(value):
    return value * 2
def test_scalar():
    assert f(3) == 6
def test_invalid_source():
    assert f(3, 0) == 6
def test_other():
    assert f(5) == 10
''')
    generated = generate(data)
    assert generated['binding_statuses']['invalid'] > 0
    assert generated['skipped']['mechanically_invalid_proposal'] > 0
    assert not any('f(5, 0)' in p['edits'][0]['after'] for p in generated['candidates'])


def test_budgets_and_candidate_byte_ids_are_deterministic(tmp_path):
    data = corpus(tmp_path, SHAPES)
    budget = Budget(max_candidates=1, max_attempts=2)
    first, second = generate(data, budget), generate(data, budget)
    assert first == second
    assert first['counts']['attempted_triples'] <= 2
    assert first['counts']['candidates'] <= 1
    assert first['skipped']['attempt_budget_remaining_triples'] > 0


def test_gate_evidence_explicitly_describes_changed_assertions(tmp_path):
    data = corpus(tmp_path, SHAPES)
    generated = generate(data)
    evidence, candidates = gate_evidence(data, generated, 'Ordinary unit requirement')
    assert candidates == generated['candidates'] and candidates
    assert 'Assertions may change' in evidence['oracle_policy']
    assert 'retained verbatim' not in evidence['oracle_policy']
    assert len(evidence['source_tests']) == 3
    json.dumps({'evidence': evidence, 'candidates': candidates})


def test_same_algorithm_handles_typescript_full_bodies(tmp_path):
    data = corpus(tmp_path, '''test('scalar', () => { expect(f(3)).toEqual(6); });
test('container', () => { expect(f([3])).toEqual([6]); });
test('other', () => { expect(f(5)).toEqual(10); });
''', 'typescript')
    generated = generate(data)
    assert any('expect(f([5])).toEqual([10])' in p['edits'][0]['after'] for p in generated['candidates'])
    emitted = emit(data, generated['candidates'])
    assert emitted['obligations'] and emitted['unsupported'] == []


def test_same_algorithm_handles_go_full_bodies(tmp_path):
    data = corpus(tmp_path, '''package shapes
import "testing"
import "github.com/stretchr/testify/require"
func TestScalar(t *testing.T) { require.Equal(t, 6, f(3)) }
func TestContainer(t *testing.T) { require.Equal(t, []int{6}, f([]int{3})) }
func TestOther(t *testing.T) { require.Equal(t, 10, f(5)) }
''', 'go')
    generated = generate(data)
    assert any('[]int{10}' in p['edits'][0]['after'] and 'f([]int{5})' in p['edits'][0]['after']
               for p in generated['candidates'])
    emitted = emit(data, generated['candidates'])
    assert emitted['obligations'] and emitted['unsupported'] == []
