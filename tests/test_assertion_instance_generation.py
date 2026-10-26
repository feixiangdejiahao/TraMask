"""Automatic bounded search over invented oracle-helper call instances."""
from collections import Counter
import json
import pytest

from prototypes.helper_assertion_instances_v01.generate import Budget, _json_provenance, generate, gate_evidence
from prototypes.test_edit_analogy_v02.generate import _refine
from generic_composition.corpus import build_corpus
from generic_composition.emitter import emit
from generic_composition.gate import presentation, selection_candidates
from generic_composition.terms import Hole, Term


HELPER = 'def verify(value, expected):\n    assert subject(value) == expected\n'
CALLS = '''def test_many():
    untouched = setup()
    verify(1, 2)
    verify([1], [2])
    verify(3, 6)
    finish(untouched)
'''


def corpus(tmp_path, code):
    (tmp_path / 'test_instances.py').write_text(code)
    return build_corpus(tmp_path, 'python')


def test_automatic_same_parent_abc_selection_and_complete_evidence(tmp_path):
    data = corpus(tmp_path, HELPER + CALLS)
    generated = generate(data)
    candidate = next(c for c in generated['candidates'] if c['edits'][0]['after'] == 'verify([3], [6])')
    assert len(set(candidate['source_instance_ids'])) == 3
    assert len(set(s['test_id'] for s in candidate['provenance']['sources'].values())) == 1
    assert generated['counts']['eligible_tests'] == 1 and generated['counts']['eligible_instances'] == 3
    assert generated['budget'] == {'max_candidates': 128, 'top_k': 10, 'max_group_tests': 64,
                                   'target_neighbors': 8, 'edit_neighbors': 12, 'max_attempts': 2000,
                                   'max_nodes': 1500, 'max_holes': 32, 'max_body_bytes': 8000}
    emitted = emit(data, [candidate])
    assert not emitted['unsupported'] and len(emitted['controls']) == 1
    evidence, candidates = gate_evidence(data, generated, 'Collection input supports element-wise results.')
    assert len(evidence['source_tests']) == 1
    assert 'finish(untouched)' in next(iter(evidence['source_tests'].values()))['code']
    assert 'assert subject(value) == expected' in next(iter(evidence['helper_definitions'].values()))['code']
    assert {i['statement'] for i in evidence['assertion_instances'].values()} >= {'verify(1, 2)', 'verify([1], [2])', 'verify(3, 6)'}
    assert 'SAME parent' in evidence['unit_policy']
    assert 'not oracle validity' in evidence['oracle_policy']
    json.dumps(generated, sort_keys=True)
    json.dumps(presentation(evidence, selection_candidates(candidates, 'ordinal_v1')), sort_keys=True)


def test_refinement_is_cached_once_per_input_instance_and_is_deterministic(tmp_path):
    data = corpus(tmp_path, HELPER + CALLS)
    counts = Counter()

    def counted(record, budget):
        counts[record['instance_id']] += 1
        return _refine(record, budget)

    first = generate(data, refine=counted)
    assert sorted(counts.values()) == [1, 1, 1]
    assert first == generate(data)
    encoded = json.dumps(first, sort_keys=True)
    assert encoded == json.dumps(generate(data), sort_keys=True)


def test_group_cap_rotates_parent_tests_before_second_round(tmp_path):
    code = HELPER + 'def test_long():\n' + ''.join(f'    verify({i}, {2*i})\n' for i in range(12))
    code += 'def test_second():\n    verify([1], [2])\n    verify([3], [6])\n'
    code += 'def test_third():\n    verify((1,), (2,))\n    verify((3,), (6,))\n'
    data = corpus(tmp_path, code)
    generated = generate(data, Budget(max_group_tests=6, max_attempts=1))
    assert len(generated['group_selection']) == 1
    selected = generated['group_selection'][0]
    assert sorted(selected['parent_test_counts'].values()) == [2, 2, 2]
    assert len(selected['instances']) == 6
    assert generated['skipped']['group_instance_budget'] == 10


def test_search_and_output_budgets_remain_separate_fixed_limits(tmp_path):
    data = corpus(tmp_path, HELPER + CALLS.replace('    finish(untouched)',
                                                 '    verify(5, 10)\n    verify(7, 14)\n    finish(untouched)'))
    bounded = generate(data, Budget(max_attempts=2, max_candidates=1))
    assert bounded['counts']['attempted_triples'] <= 2
    assert bounded['counts']['candidates'] <= 1
    assert bounded == generate(data, Budget(max_attempts=2, max_candidates=1))


def test_existing_statement_with_different_trivia_is_excluded_and_edits_are_unique(tmp_path):
    data = corpus(tmp_path, HELPER + CALLS.replace('    finish(untouched)',
        '    verify( [3] , [6] )\n    verify([3], [6])\n    verify(5, 10)\n    finish(untouched)'))
    generated = generate(data)
    assert generated['skipped']['existing_combination'] > 0
    assert not any(c['edits'][0]['after'] == 'verify([3], [6])' for c in generated['candidates'])
    keys = [(c['base_test_id'], c['edits'][0]['span']['start_byte'], c['edits'][0]['after'])
            for c in generated['candidates']]
    assert len(keys) == len(set(keys))
    assert any(c['edits'][0]['after'] == 'verify([5], [10])' for c in generated['candidates'])
    assert generated['skipped']['duplicate_target_edit'] > 0


def test_json_cleanup_removes_internal_term_keyed_substitutions_recursively():
    raw = {'provenance': {'source_substitutions': {Hole('expr', 0): Term('integer', '3')},
                          'nested': {'target_substitutions': {Hole('expr', 0): Term('integer', '4')},
                                     'checks': {'reconstruct': True}}}}
    cleaned = _json_provenance(raw)
    assert cleaned == {'provenance': {'nested': {'checks': {'reconstruct': True}}}}
    json.dumps(cleaned)


def test_helper_granularity_generator_does_not_implicitly_add_full_body_search(tmp_path):
    data = corpus(tmp_path, 'def test_a():\n    assert f(1) == 2\ndef test_b():\n    assert f([1]) == [2]\ndef test_c():\n    assert f(3) == 6\n')
    generated = generate(data)
    assert generated['counts']['eligible_instances'] == 0
    assert generated['counts']['attempted_triples'] == 0
    assert not generated['candidates']


@pytest.mark.parametrize('language,path,code,wanted', [
    ('go', 'instances_test.go', '''package toy
import "testing"
import "github.com/stretchr/testify/require"
func check(t *testing.T, input interface{}, want interface{}) { require.Equal(t, want, subject(input)) }
func TestMany(t *testing.T) {
 check(t, 1, 2)
 check(t, []int{1}, []int{2})
 check(t, 3, 6)
}
''', 'check(t, []int{3}, []int{6})'),
    ('typescript', 'instances.test.ts', '''import { expect, test } from 'vitest';
function check(input, want) { expect(subject(input)).toEqual(want); }
test('many', () => {
 check(1, 2);
 check([1], [2]);
 check(3, 6);
});
''', 'check([3], [6]);'),
])
def test_driver_uses_valid_host_statement_novelty_across_languages(tmp_path, language, path, code, wanted):
    (tmp_path / path).write_text(code)
    data = build_corpus(tmp_path, language)
    generated = generate(data)
    selected = [c for c in generated['candidates'] if c['edits'][0]['after'] == wanted]
    assert selected and not emit(data, selected)['unsupported']
    json.dumps(generated)
