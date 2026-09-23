"""Open-term binding/effect examples; builders and subject are never run."""
from itertools import permutations
import json

import pytest

from generic_composition.corpus import build_corpus
from generic_composition.emitter import emit
from experimental.assertion_instances.core import extract as closed_extract
from experimental.assertion_instances.generate import _json_provenance
from experimental.assertion_instances_v2.core import extract, compose
from experimental.assertion_instances_v2.generate import Budget, generate, novelty, gate_evidence
from generic_composition.gate import presentation, selection_candidates


HELPER = 'def verify(value, expected):\n    assert subject(value) == expected\n'


def corpus(tmp_path, text, language='python'):
    path = {'python': 'test_env.py', 'go': 'env_test.go', 'typescript': 'env.test.ts'}[language]
    (tmp_path / path).write_text(text)
    return build_corpus(tmp_path, language)


def all_results(data):
    extracted = extract(data)
    return extracted, [compose(data, *triple) for triple in permutations(extracted['instances'], 3)]


def matching(rows, text):
    return next(r for r in rows if r['status'] == 'hypothesis' and r['candidate']['edits'][0]['after'] == text)


def test_bound_locals_travel_by_port_and_resolve_in_preserved_parent(tmp_path):
    text = HELPER + '''def test_many():
    small = 1
    large = 3
    verify(small, 2)
    verify([small], [2])
    verify(large, 6)
'''
    data = corpus(tmp_path, text)
    assert not closed_extract(data)['instances']
    extracted, rows = all_results(data)
    assert len(extracted['instances']) == 3
    proposal = matching(rows, 'verify([large], [6])')['candidate']
    check = proposal['provenance']['lexical_check']
    assert check['status'] == 'compatible'
    assert next(r for r in check['references'] if r['name'] == 'large')['binding'][0] == 'lexical_binding'
    assert proposal['provenance']['binding_correspondences'][0]['claim'].endswith('not_value_equivalence')
    assert not emit(data, [proposal])['unsupported']
    assert (tmp_path / 'test_env.py').read_text() == text
    json.dumps(_json_provenance(proposal))


def test_module_constants_and_source_defined_expected_builder_are_preserved(tmp_path):
    data = corpus(tmp_path, HELPER + '''SMALL = 1
LARGE = 3
def expected(value):
    raise RuntimeError("this builder must never be executed by generation")
def test_many():
    verify(SMALL, expected(2))
    verify([SMALL], [expected(2)])
    verify(LARGE, expected(6))
''')
    extracted, rows = all_results(data)
    proposal = matching(rows, 'verify([LARGE], [expected(6)])')['candidate']
    source_c = proposal['provenance']['source_environments']['C']
    assert any(r['name'] == 'LARGE' and r['declaration']['code'] == 'LARGE = 3' for r in source_c['references'])
    assert any(r['name'] == 'expected' and 'must never be executed' in r['declaration']['code'] for r in source_c['references'])
    assert 'oracle_validity' in proposal['provenance']['lexical_check']['unproved']
    assert len(extracted['instances']) == 3


def test_same_name_different_binding_is_rejected_instead_of_captured(tmp_path):
    data = corpus(tmp_path, HELPER + '''def test_a():
    verify(1, 2)
def test_b():
    extra = 9
    verify([1, extra], [2, extra])
def test_c():
    extra = 999
    verify(3, 6)
''')
    extracted = extract(data)
    A, B, C = extracted['instances']
    result = compose(data, A, B, C)
    assert result['status'] == 'unsupported'
    assert result['reason'] == 'binding_capture_or_missing_reference'
    assert result['lexical_check']['name'] == 'extra'
    assert result['lexical_check']['expected_binding'] != result['lexical_check']['actual_binding']


def test_same_spelling_a_c_bindings_can_be_explicitly_corresponded_without_equality_claim(tmp_path):
    data = corpus(tmp_path, HELPER + '''def test_ab():
    x = 1
    verify(x, 2)
    verify([x], [2])
def test_c():
    x = 3
    verify(x, 6)
''')
    result = compose(data, *extract(data)['instances'])
    assert result['status'] == 'hypothesis'
    proposal = result['candidate']
    assert proposal['edits'][0]['after'] == 'verify([x], [6])'
    pair = proposal['provenance']['binding_correspondences'][0]
    assert pair['same_spelling'] and pair['A']['binding'] != pair['C']['binding']
    actual = next(r for r in proposal['provenance']['lexical_check']['references'] if r['name'] == 'x')
    assert actual['binding'] == pair['C']['binding']
    assert pair['claim'].endswith('not_value_equivalence')


def test_b_only_local_missing_from_c_is_rejected(tmp_path):
    data = corpus(tmp_path, HELPER + '''def test_a():
    verify(1, 2)
def test_b():
    extra = 9
    verify([1, extra], [2, extra])
def test_c():
    verify(3, 6)
''')
    result = compose(data, *extract(data)['instances'])
    assert result['status'] == 'unsupported'
    assert result['reason'] == 'binding_capture_or_missing_reference'


def test_source_argument_calls_retain_effect_evidence_without_purity_claim(tmp_path):
    data = corpus(tmp_path, HELPER + '''events = []
def make(value):
    events.append(value)
    return value
def test_many():
    verify(make(1), 2)
    verify([make(1)], [2])
    verify(make(3), 6)
''')
    _, rows = all_results(data)
    proposal = matching(rows, 'verify([make(3)], [6])')['candidate']
    environments = proposal['provenance']['source_environments']
    assert any(c['text'] == 'make(3)' and c['effects'] == 'unknown' for c in environments['C']['calls'])
    assert 'effects' in environments['C']['unproved']
    assert any('events.append' in (r['declaration'] or {}).get('code', '') for r in environments['C']['references'])


def test_shared_source_variable_in_actual_and_expected_does_not_merge_roles(tmp_path):
    data = corpus(tmp_path, HELPER + '''def test_many():
    both = 1
    input_value = 2
    want = 7
    verify(both, both)
    verify([both], [both])
    verify(input_value, want)
''')
    _, rows = all_results(data)
    proposal = matching(rows, 'verify([input_value], [want])')['candidate']
    assert len(proposal['provenance']['binding_correspondences']) == 2


def test_definition_after_target_call_is_resolved_with_adjusted_byte_offsets(tmp_path):
    data = corpus(tmp_path, '''# 前缀
def test_many():
    verify(make(1), 2)
    verify([make(1)], [2])
    verify(make(3), 6)
def make(value):
    return value
''' + HELPER)
    _, rows = all_results(data)
    proposal = matching(rows, 'verify([make(3)], [6])')['candidate']
    assert proposal['provenance']['lexical_check']['status'] == 'unknown'  # Deferred global initialization, not rejected.
    assert not emit(data, [proposal])['unsupported']


@pytest.mark.parametrize('language,code,wanted', [
    ('go', '''package toy
import "testing"
import "github.com/stretchr/testify/require"
func verify(t *testing.T, value interface{}, expected interface{}) { require.Equal(t, expected, subject(value)) }
func TestMany(t *testing.T) {
 small := 1
 large := 3
 verify(t, small, 2)
 verify(t, []int{small}, []int{2})
 verify(t, large, 6)
}
''', 'verify(t, []int{large}, []int{6})'),
    ('typescript', '''import { expect, test } from 'vitest';
function verify(value, wanted) { expect(subject(value)).toEqual(wanted); }
test('many', () => {
 const small = 1;
 const large = 3;
 verify(small, 2);
 verify([small], [2]);
 verify(large, 6);
});
''', 'verify([large], [6]);'),
])
def test_open_lexical_environment_uses_language_scopes(tmp_path, language, code, wanted):
    data = corpus(tmp_path, code, language)
    _, rows = all_results(data)
    proposal = matching(rows, wanted)['candidate']
    assert not emit(data, [proposal])['unsupported']


def test_inline_binder_is_explicitly_outside_small_environment_adapter(tmp_path):
    data = corpus(tmp_path, HELPER + 'def test_many():\n    verify(lambda x: x, 2)\n')
    extracted = extract(data)
    assert not extracted['instances']
    assert extracted['skipped'] == {'binder_inside_instance_requires_scope_transport': 1}


def test_novelty_does_not_equate_same_spelling_with_different_bindings(tmp_path):
    data = corpus(tmp_path, HELPER + '''def test_a():
    x = 1
    verify(x, 2)
    verify( x , 2 )
def test_b():
    x = 9
    verify(x, 2)
''')
    first, formatted, distinct = extract(data)['instances']
    assert novelty(first) == novelty(formatted)
    assert novelty(first) != novelty(distinct)


def test_gate_includes_full_lexical_declarations_and_unknown_effects(tmp_path):
    data = corpus(tmp_path, HELPER + '''SMALL = 1
LARGE = 3
def builder(value):
    side_effect(value)
    return value
def test_many():
    verify(SMALL, builder(2))
    verify([SMALL], [builder(2)])
    verify(LARGE, builder(6))
''')
    _, rows = all_results(data)
    result = matching(rows, 'verify([LARGE], [builder(6)])')
    generated = _json_provenance({'candidates': [result['candidate']], 'rules': [result['rule']]})
    evidence, _ = gate_evidence(data, generated, 'Use collection inputs.')
    declarations = [d['code'] for d in evidence['lexical_declarations'].values()]
    assert 'LARGE = 3' in declarations
    assert any('side_effect(value)' in code for code in declarations)
    assert 'never value-equivalence claims' in evidence['environment_policy']
    assert all('effects' in env['unproved'] for env in evidence['lexical_environments'].values())
    json.dumps(evidence)


def test_wrapper_uses_same_driver_budgets_and_emits_json_candidates(tmp_path):
    data = corpus(tmp_path, HELPER + '''def test_many():
    small = 1
    large = 3
    verify(small, 2)
    verify([small], [2])
    verify(large, 6)
''')
    generated = generate(data)
    proposals = [c for c in generated['candidates'] if c['edits'][0]['after'] == 'verify([large], [6])']
    assert proposals and not emit(data, proposals)['unsupported']
    assert generated['counts']['eligible_instances'] == 3
    assert generated == generate(data)
    bounded = generate(data, Budget(max_attempts=1, max_candidates=1))
    assert bounded['counts']['attempted_triples'] <= 1 and bounded['counts']['candidates'] <= 1
    json.dumps(generated, sort_keys=True)
    evidence, candidates = gate_evidence(data, generated, 'Collection input is valid.')
    json.dumps(presentation(evidence, selection_candidates(candidates, 'ordinal_v1')))


def test_wrapper_novelty_uses_binding_ids_and_ignores_trivia(tmp_path):
    data = corpus(tmp_path, HELPER + '''def test_many():
    small = 1
    large = 3
    verify(small, 2)
    verify([small], [2])
    verify(large, 6)
    verify( [large] , [6] )
''')
    generated = generate(data)
    assert generated['skipped']['existing_combination'] > 0
    assert not any(c['edits'][0]['after'] == 'verify([large], [6])' for c in generated['candidates'])


@pytest.mark.parametrize('language,code,wanted', [
    ('go', '''package toy
import "testing"
import "github.com/stretchr/testify/require"
func verify(t *testing.T, value interface{}, expected interface{}) { require.Equal(t, expected, subject(value)) }
func TestMany(t *testing.T) {
 small := 1
 large := 3
 verify(t, small, 2)
 verify(t, []int{small}, []int{2})
 verify(t, large, 6)
}
''', 'verify(t, []int{large}, []int{6})'),
    ('typescript', '''import { expect, test } from 'vitest';
function verify(value, wanted) { expect(subject(value)).toEqual(wanted); }
test('many', () => {
 const small = 1;
 const large = 3;
 verify(small, 2);
 verify([small], [2]);
 verify(large, 6);
});
''', 'verify([large], [6]);'),
])
def test_wrapper_go_and_typescript_novelty_retain_binding_origins(tmp_path, language, code, wanted):
    data = corpus(tmp_path, code, language)
    generated = generate(data)
    proposals = [c for c in generated['candidates'] if c['edits'][0]['after'] == wanted]
    assert proposals and not emit(data, proposals)['unsupported']
    json.dumps(generated)
