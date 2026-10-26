"""Independent source-only composition tests for contiguous assertion windows."""
import json
import pytest

from generic_composition.corpus import build_corpus, source_text
from generic_composition.emitter import emit
from generic_composition.gate import presentation, selection_candidates
from prototypes.assertion_window_generation.generate import Budget, generate, gate_evidence
from prototypes.assertion_window_generation.compose import compose, prepare_environment
from prototypes.assertion_window_generation.extract import extract


def corpus(tmp_path, code, language='python'):
    path = {'python': 'test_windows.py', 'go': 'windows_test.go', 'typescript': 'windows.test.ts'}[language]
    (tmp_path / path).write_text(code)
    return build_corpus(tmp_path, language)


NATIVE = '''def test_a():
    x = 1
    assert f(x) == 2
def test_b():
    x = 1
    assert f([x]) == [2]
def test_c():
    resource = acquire()
    y = 3
    note = touch()
    assert f(y) == 6
    cleanup(resource, note)
'''


def test_native_assert_window_keeps_C_gap_and_parent_prefix_suffix(tmp_path):
    data = corpus(tmp_path, NATIVE)
    generated = generate(data)
    expected = 'y = 3\n    note = touch()\n    assert f([y]) == [6]'
    candidate = next(c for c in generated['candidates'] if c['edits'][0]['after'] == expected)
    edit = candidate['edits'][0]
    assert source_text(data, edit['span']) == 'y = 3\n    note = touch()\n    assert f(y) == 6'
    assert candidate['provenance']['C_protected_gaps_preserved_exactly_once_in_order']
    assert all(candidate['provenance']['checks'].values())
    output = emit(data, [candidate])
    assert not output['unsupported']
    text = output['files']['test_windows.py']
    assert text.count('resource = acquire()') == 3
    assert text.count('note = touch()') == 3
    assert text.count('cleanup(resource, note)') == 3
    assert (tmp_path / 'test_windows.py').read_text() == NATIVE
    evidence, candidates = gate_evidence(data, generated, 'The API accepts collections.')
    assert 'COMPLETE edited parent' in evidence['oracle_policy']
    assert any('cleanup(resource, note)' in row['code'] for row in evidence['source_tests'].values())
    json.dumps(generated, sort_keys=True)
    json.dumps(presentation(evidence, selection_candidates(candidates, 'ordinal_v1')))


def test_cross_parent_local_helper_setup_is_part_of_the_same_unit(tmp_path):
    data = corpus(tmp_path, '''def verify(value, expected):
    assert f(value) == expected
def test_a():
    x = 1
    verify(x, 2)
def test_b():
    x = 1
    verify([x], [2])
def test_c():
    y = 3
    verify(y, 6)
''')
    generated = generate(data)
    proposals = [c for c in generated['candidates'] if c['edits'][0]['after'] == 'y = 3\n    verify([y], [6])']
    assert proposals and not emit(data, proposals)['unsupported']
    assert len({s['test_id'] for s in proposals[0]['provenance']['sources'].values()}) == 3


def test_contiguous_window_preserves_mutation_setup_without_executing_it(tmp_path):
    data = corpus(tmp_path, '''def verify(value, expected):
    assert f(value) == expected
def test_a():
    xs = []
    xs.append(1)
    verify(xs, [2])
def test_b():
    xs = []
    xs.append(1)
    verify([xs], [[2]])
def test_c():
    xs = []
    xs.append(3)
    verify(xs, [6])
''')
    generated = generate(data)
    desired = 'xs = []\n    xs.append(3)\n    verify([xs], [[6]])'
    assert any(c['edits'][0]['after'] == desired for c in generated['candidates'])


def test_liveout_assertion_is_retained_and_exposed_to_gate_not_declared_safe(tmp_path):
    data = corpus(tmp_path, '''def verify(value, expected):
    assert f(value) == expected
def test_a():
    x = 1
    verify(x, 2)
def test_b():
    x = [1]
    verify(x, [2])
def test_c():
    y = 3
    verify(y, 6)
    assert isinstance(y, int)
''')
    generated = generate(data)
    proposal = next(c for c in generated['candidates'] if c['edits'][0]['after'] == 'y = [3]\n    verify(y, [6])')
    # This is intentionally not a valid full-parent oracle: it is a gate
    # counterexample. Mechanical reconstruction must not hide the later assert.
    assert proposal['oracle']['semantic_status'] == 'requires_admission'
    assert 'liveout_effects' in proposal['provenance']['lexical_check']['unproved']
    emitted = emit(data, [proposal])
    assert 'assert isinstance(y, int)' in emitted['files']['test_windows.py']
    evidence, _ = gate_evidence(data, generated, 'Collection inputs are allowed.')
    assert 'changed live-out definitions' in evidence['oracle_policy']


def test_protected_C_gap_is_not_allowed_to_become_a_rewritten_anchor(tmp_path):
    code = NATIVE.replace('    x = 1\n', '    x = 1\n    note = touch()\n')
    code = code.replace('    note = touch()\n    assert f([x])', '    note = touch() + 1\n    assert f([x])')
    data = corpus(tmp_path, code)
    cache = {}
    rows = [prepare_environment(data, r, cache) for r in extract(data)['instances']]
    rows.sort(key=lambda r: r['test']['name'])
    A, B, C = rows
    result = compose(data, A, B, C)
    assert result['status'] == 'unsupported'
    assert result['reason'] == 'protected_C_gap_changed_or_reordered'


def test_common_protected_gap_can_remain_an_anchor_if_bytes_and_order_are_preserved(tmp_path):
    data = corpus(tmp_path, NATIVE.replace('    x = 1\n', '    x = 1\n    note = touch()\n'))
    generated = generate(data)
    proposal = next(c for c in generated['candidates'] if c['edits'][0]['after'] ==
                    'y = 3\n    note = touch()\n    assert f([y]) == [6]')
    assert proposal['provenance']['protected_gap_witnesses'] == [
        {'source_statement': 1, 'output_statement': 1, 'alignment_role': 'anchor'}]


def test_fixed_budgets_and_deterministic_window_generation(tmp_path):
    data = corpus(tmp_path, NATIVE)
    result = generate(data, Budget(max_attempts=2, max_candidates=1))
    assert result['counts']['attempted_triples'] <= 2
    assert result['counts']['candidates'] <= 1
    assert result == generate(data, Budget(max_attempts=2, max_candidates=1))
    assert 'alternative order is not searched' in result['gap_order_policy']


@pytest.mark.parametrize('language,code,expected', [
    ('go', '''package toy
import "testing"
func TestA(t *testing.T) { got := f(1); if got != 2 { t.Fatal(got) } }
func TestB(t *testing.T) { got := f(-1); if got != -2 { t.Fatal(got) } }
func TestC(t *testing.T) { got := f(3); if got != 6 { t.Fatal(got) } }
''', 'got := f(-3); if got != -6 { t.Fatal(got) }'),
    ('typescript', '''import { expect, test } from 'vitest';
test('a', () => { const x = 1; expect(f(x)).toEqual(2); });
test('b', () => { const x = 1; expect(f([x])).toEqual([2]); });
test('c', () => { const y = 3; expect(f(y)).toEqual(6); });
''', 'const y = 3; expect(f([y])).toEqual([6]);'),
])
def test_native_multilanguage_windows_are_source_editable(tmp_path, language, code, expected):
    data = corpus(tmp_path, code, language)
    generated = generate(data)
    proposals = [c for c in generated['candidates'] if c['edits'][0]['after'] == expected]
    assert proposals and not emit(data, proposals)['unsupported']
    json.dumps(generated)
