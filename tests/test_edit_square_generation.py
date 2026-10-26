"""Full automatic alternative-generator tests, without pilot or model data."""
import json

import pytest

from generic_composition.corpus import build_corpus
from generic_composition.emitter import emit
from generic_composition.gate import presentation, selection_candidates
from generic_composition.terms import render
from prototypes.test_edit_square_generation.generate import Budget, _parse_body, generate, gate_evidence


CASES = [
    ('python', 'test_square.py', '''def test_A():
    assert f(1) == 2
def test_B():
    assert f([1]) == [2]
def test_C():
    assert f(3) == 6
''', 'assert f([3]) == [6]'),
    ('go', 'square_test.go', '''package square
import "testing"
import "github.com/stretchr/testify/require"
func TestA(t *testing.T) { require.Equal(t, 2, f(1)) }
func TestB(t *testing.T) { require.Equal(t, []int{2}, f([]int{1})) }
func TestC(t *testing.T) { require.Equal(t, 6, f(3)) }
''', 'require.Equal(t, []int{6}, f([]int{3}))'),
    ('typescript', 'square.test.ts', '''test('A', () => { expect(f(1)).toEqual(2); });
test('B', () => { expect(f([1])).toEqual([2]); });
test('C', () => { expect(f(3)).toEqual(6); });
''', 'expect(f([3])).toEqual([6])'),
]


@pytest.mark.parametrize('language,path,code,expected', CASES)
def test_automatic_generation_json_and_emitter_for_each_language(tmp_path,language,path,code,expected):
    (tmp_path / path).write_text(code)
    corpus = build_corpus(tmp_path, language)
    generated = generate(corpus)
    matches = [p for p in generated['candidates'] if expected in p['edits'][0]['after']]
    assert matches
    candidate = matches[0]
    assert candidate['oracle']['mode'] == 'merge_source_edits'
    assert 'source_test_id' not in candidate['oracle']
    assert 'alignment' not in candidate
    assert candidate['provenance']['kernel'] == 'lexical_edit_square_v1'
    assert all(candidate['provenance']['checks'].values())
    emitted = emit(corpus, [candidate])
    assert emitted['unsupported'] == [] and len(emitted['obligations']) == 1
    json.dumps(generated)


def test_shared_driver_budget_and_gate_describe_two_sided_assertion_edits(tmp_path):
    language, path, code, _ = CASES[0]
    (tmp_path / path).write_text(code)
    corpus = build_corpus(tmp_path, language)
    small = generate(corpus, Budget(max_attempts=2, max_candidates=1))
    assert small['counts']['attempted_triples'] <= 2
    assert small['counts']['attempted_merge_results'] <= 4
    assert small['counts']['candidates'] <= 1
    assert small == generate(corpus, Budget(max_attempts=2, max_candidates=1))
    generated = generate(corpus)
    evidence, candidates = gate_evidence(corpus, generated, 'Elementwise function requirement')
    shown = presentation(evidence, selection_candidates(candidates, 'ordinal_v1'))
    assert 'both source-relative edits' in evidence['oracle_policy']
    assert 'not solely copied from B' in evidence['oracle_policy']
    assert 'not an aligned-residual guarantee' in evidence['composition_policy']
    assert all(p['rule_id'] in evidence['merge_edits'] for p in shown['candidates'])
    json.dumps(shown)


@pytest.mark.parametrize('language,code', [
    ('python', 'assert f(] == 2'),
    ('go', '{ f(] }'),
    ('typescript', '{ f(] }'),
])
def test_invalid_merged_body_cannot_become_a_candidate(language,code):
    with pytest.raises(ValueError, match='body_syntax_error'):
        _parse_body(code, language, '    ', 1000)


@pytest.mark.parametrize('language,code,indent', [
    ('python', 'x = f(1)\n        assert x == 2\n', '        '),
    ('go', '{ x := f(1); check(x, 2) }', ''),
    ('typescript', '{ const x = f(1); check(x, 2); }', ''),
])
def test_fake_wrapper_parser_preserves_every_merged_byte(language,code,indent):
    assert render(_parse_body(code, language, indent, 1000)) == code


def test_parameter_rows_still_merge_joint_input_and_expected(tmp_path):
    (tmp_path / 'test_rows.py').write_text('''import pytest
@pytest.mark.parametrize("value,want", [(1,1),([1],[1]),(2,7)])
def test_table(value,want):
    assert f(value) == want
''')
    corpus = build_corpus(tmp_path, 'python')
    generated = generate(corpus)
    matches = [p for p in generated['candidates'] if 'value = [2]' in p['edits'][0]['after']
               and 'want = [7]' in p['edits'][0]['after']]
    assert matches
    assert emit(corpus, [matches[0]])['unsupported'] == []


def test_valid_source_tests_with_invalid_merged_assertion_are_counted(tmp_path):
    (tmp_path / 'test_messages.py').write_text('''def test_A():
    assert f(1) == 2
def test_B():
    assert f(1) == 2, "B"
def test_C():
    assert f(1) == 2, "C"
''')
    generated = generate(build_corpus(tmp_path, 'python'))
    # Both sides add an assertion message at the same source position. Neither
    # merge order yields valid Python; rejection occurs before candidate/gate.
    assert generated['counts']['attempted_triples'] > 0
    assert generated['skipped']['analogy:edit_square:body_syntax_error'] > 0
    assert generated['candidates'] == []
