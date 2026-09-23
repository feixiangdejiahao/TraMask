"""Invented source-only examples; no repository program is run for an oracle."""
from itertools import permutations
import json

import pytest

from experimental.assertion_instances.core import compose, extract
from generic_composition.corpus import build_corpus, source_text
from generic_composition.emitter import emit
from generic_composition.terms import render


PY_HELPER = 'def verify(input, expected):\n    assert subject(input) == expected\n\n'
GO_HELPER = '''package example
import "testing"
import "github.com/stretchr/testify/require"
func verify(t *testing.T, input interface{}, expected interface{}) {
 require.Equal(t, expected, subject(input))
}
'''


def corpus(tmp_path, code, language='python'):
    path = {'python': 'test_instances.py', 'go': 'instances_test.go',
            'typescript': 'instances.test.ts'}[language]
    (tmp_path / path).write_text(code)
    return build_corpus(tmp_path, language)


def candidates(data):
    extracted = extract(data)
    generated = [compose(data, *triple) for triple in permutations(extracted['instances'], 3)]
    return extracted, [r['candidate'] for r in generated if r['status'] == 'hypothesis']


def test_same_parent_instances_generate_fourth_call_without_cloning_setup(tmp_path):
    code = PY_HELPER + '''def test_many(context):
    state = prepare()
    verify(1, 2)
    verify([1], [2])
    verify(3, 6)
    finish(state)
'''
    data = corpus(tmp_path, code)
    extracted, generated = candidates(data)
    assert extracted['unsupported'] == []
    assert len({r['instance_id'] for r in extracted['instances']}) == 3
    assert len({r['parent_test_id'] for r in extracted['instances']}) == 1
    candidate = next(c for c in generated if c['edits'][0]['after'] == 'verify([3], [6])')
    assert candidate['edits'][0]['before'] == 'verify(3, 6)'
    output = emit(data, [candidate])
    assert output['unsupported'] == [] and len(output['controls']) == 1
    code_after = output['files']['test_instances.py']
    # Original, one generated parent, and one source-control parent each keep
    # preparation/finalization exactly once. Nothing is added to helper code.
    assert code_after.count('state = prepare()') == 3
    assert code_after.count('finish(state)') == 3
    assert code_after.count('verify([3], [6])') == 1
    assert (tmp_path / 'test_instances.py').read_text() == code
    assert all(candidate['provenance']['checks'].values())
    assert candidate['oracle']['semantic_status'] == 'requires_admission'
    json.dumps(candidate)


@pytest.mark.parametrize('language,code,expected', [
    ('go', GO_HELPER + '''func TestMany(t *testing.T) {
 verify(t, "a", "A")
 verify(t, "[a]", "[A]")
 verify(t, "b", "B")
}
''', 'verify(t, "[b]", "[B]")'),
    ('typescript', '''import { expect, test } from 'vitest';
function verify(input, expected) { expect(subject(input)).toEqual(expected); }
test('many', () => {
 verify(1, 2);
 verify([1], [2]);
 verify(3, 6);
});
''', 'verify([3], [6]);'),
])
def test_language_neutral_call_adapter(language, code, expected, tmp_path):
    data = corpus(tmp_path, code, language)
    extracted, generated = candidates(data)
    assert len(extracted['instances']) == 3 and not extracted['unsupported']
    candidate = next(c for c in generated if c['edits'][0]['after'] == expected)
    assert not emit(data, [candidate])['unsupported']


def test_same_value_input_and_oracle_keep_separate_source_ports(tmp_path):
    data = corpus(tmp_path, PY_HELPER + '''def test_many():
    verify(1, 1)
    verify([1], [1])
    verify(2, 7)
''')
    extracted, generated = candidates(data)
    candidate = next(c for c in generated if c['edits'][0]['after'] == 'verify([2], [7])')
    for instance in extracted['instances']:
        assert render(instance['tree'].term) == source_text(data, instance['span'])
        assert [p['roles'] for p in instance['ports']] == [['observed'], ['expected']]
        for port in instance['ports']:
            assert source_text(data, port['actual']['span']) == port['actual']['text']
    assert candidate['provenance']['source_assertion_ports']['A'][0]['actual']['span'] != \
           candidate['provenance']['source_assertion_ports']['A'][1]['actual']['span']


def test_unicode_and_reordered_keyword_bindings_are_source_backed(tmp_path):
    data = corpus(tmp_path, '# 前置多字节\n' + PY_HELPER + '''def test_many():
    verify(expected="相同", input="相同")
    verify(expected=["相同"], input=["相同"])
    verify(expected="结果", input="输入")
''')
    extracted, generated = candidates(data)
    assert any(c['edits'][0]['after'] == 'verify(expected=["结果"], input=["输入"])' for c in generated)
    for instance in extracted['instances']:
        assert source_text(data, instance['span']) == instance['text']
        ports = {p['parameter']: p for p in instance['ports']}
        assert ports['input']['keyword'] == 'input'
        assert ports['expected']['keyword'] == 'expected'
        assert ports['input']['actual']['span']['start_byte'] > ports['expected']['actual']['span']['start_byte']


def test_go_closed_aggregate_and_predeclared_conversion_admission(tmp_path):
    data = corpus(tmp_path, GO_HELPER + '''type Item struct { Value int }
func TestMany(t *testing.T) {
 verify(t, map[string]int{"x": 1}, struct{ Value int }{Value: 2})
 verify(t, &Item{Value: 3}, int64(3))
 verify(t, []int{1, 2}, [2]int{1, 2})
 verify(t, []map[string]int{{"x": 1}}, -3)
}
''', 'go')
    extracted = extract(data)
    assert len(extracted['instances']) == 4 and not extracted['unsupported']
    # These were not already recognized as host-language literal values.
    assert any(not p['actual']['literal_known'] and p['actual']['kind'] == 'composite_literal'
               for r in extracted['instances'] for p in r['ports'])
    assert all('aliasing' in r['unproved'] for r in extracted['instances'])


def test_go_aggregate_is_transported_with_its_expected_argument(tmp_path):
    data = corpus(tmp_path, GO_HELPER + '''func TestMany(t *testing.T) {
 verify(t, 3, 6)
 verify(t, []int{3}, []int{6})
 verify(t, 4, 8)
}
''', 'go')
    _, generated = candidates(data)
    assert any(c['edits'][0]['after'] == 'verify(t, []int{4}, []int{8})' for c in generated)


@pytest.mark.parametrize('statement,setup,reason', [
    ('verify(t, map[string]int{key: 1}, 2)', 'key := "x"', 'argument_requires_external_local_state_or_computation'),
    ('verify(t, int64(3), 3)', 'int64 := func(x int) int { return x }', 'argument_call_is_not_an_unshadowed_predeclared_conversion'),
    ('verify(t, makeValue(3), 3)', '', 'argument_call_is_not_an_unshadowed_predeclared_conversion'),
    ('verify(t, 1, 2)', 't = replacement', 'caller_parameter_reassigned_before_instance'),
])
def test_go_does_not_mistake_local_state_or_shadowed_calls_for_literals(tmp_path, statement, setup, reason):
    data = corpus(tmp_path, GO_HELPER + f'func TestMany(t *testing.T) {{\n {setup}\n {statement}\n}}\n', 'go')
    extracted = extract(data)
    assert not extracted['instances']
    assert extracted['skipped'][reason] == 1


@pytest.mark.parametrize('body,reason', [
    ('    value = 1\n    verify(value, 2)', 'argument_requires_external_local_state_or_computation'),
    ('    verify(make_value(), 2)', 'argument_requires_external_local_state_or_computation'),
    ('    context = other\n    verify(context, 2)', 'caller_parameter_not_available_as_original_binding'),
    ('    if context:\n        verify(1, 2)', 'not_a_direct_parent_test_statement'),
    ('    verify(*context)', 'helper_argument_binding_unknown'),
])
def test_boundaries_are_explicit_without_helper_name_rules(tmp_path, body, reason):
    data = corpus(tmp_path, PY_HELPER + 'def test_many(context):\n' + body + '\n')
    extracted = extract(data)
    assert not extracted['instances']
    assert extracted['skipped'][reason] == 1


def test_names_alone_do_not_create_oracle_instances(tmp_path):
    data = corpus(tmp_path, '''def assert_everything(value, expected):
    return subject(value)
def test_many():
    assert_everything(1, 2)
    assert_everything([1], [2])
    assert_everything(3, 6)
''')
    assert extract(data)['instances'] == []


def test_helper_source_mapping_does_not_override_actual_lexical_shadowing(tmp_path):
    data = corpus(tmp_path, PY_HELPER + '''def test_many():
    verify = lambda x, y: None
    verify(1, 2)
''')
    assert data['capsules'][0]['helper_assertions']  # Existing syntactic mapping.
    extracted = extract(data)
    assert not extracted['instances']
    assert extracted['skipped'] == {'helper_callee_binding_not_proved': 1}


def test_helper_definition_may_follow_parent_test(tmp_path):
    data = corpus(tmp_path, 'def test_many():\n    verify(1, 2)\n\n' + PY_HELPER)
    extracted = extract(data)
    assert len(extracted['instances']) == 1 and not extracted['unsupported']


def test_extraction_budget_is_stable_and_records_rejected_source_spans(tmp_path):
    data = corpus(tmp_path, PY_HELPER + 'def test_many():\n    verify(1, 2)\n    verify(3, 4)\n')
    result = extract(data, max_instances=1)
    assert len(result['instances']) == 1 and result['skipped'] == {'instance_budget': 1}
    assert source_text(data, result['unsupported'][0]['span']) == 'verify(3, 4)'
    assert result == extract(data, max_instances=1)
