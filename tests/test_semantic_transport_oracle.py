"""Independent toys for observation transport; no subject repositories or case data."""
import ast
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from prototypes.test_action_and_oracle_transfer.oracle import (
    Limits, OracleError, Unknown, decode_value, emit_literal, encode_value,
    evaluate_expression, parse_source_literal, unknown, validate_completions,
)


def candidate(pre=(['a'],), arg=('b',), **extra):
    return {'candidate_id': 'c0', 'language': 'python',
            'pre': list(pre), 'arg': list(arg), 'observations': [{'type': 'list'}], **extra}


def test_canonical_json_does_not_reorder_source_mapping_values():
    value = {'z': {'second': 2, 'first': 1}, 'a': 3}
    wire = json.loads(json.dumps(encode_value(value), sort_keys=True))
    restored = decode_value(wire)
    assert list(restored) == ['z', 'a']
    assert list(restored['z']) == ['second', 'first']
    assert evaluate_expression('list(pre[0])', pre=[restored]) == ['z', 'a']


def completion(expected='pre[0] + [arg[0]]', guard=None, **extra):
    return {'completions': [{'candidate_id': 'c0', 'observe': 0,
                            'expected': expected, 'guard': guard, **extra}]}


def reason(payload, candidates=None):
    result = validate_completions(payload, candidates or [candidate()])
    assert not result['accepted']
    return result['rejected'][0]['code']


def test_stateful_alias_toy_combines_source_expectations_without_running_an_oracle():
    class Tape:
        def __init__(self):
            self.items = []

        def put(self, value):
            self.items[:] = [value]  # Defect: a second put overwrites the first.

        def snapshot(self):
            return self.items[:]

    for value in ['a', 'b']:
        tape = Tape()
        tape.put(value)
        assert tape.snapshot() == [value]
    result = validate_completions(completion(), [candidate(witnesses=[
        {'pre': [[]], 'arg': ['b'], 'after': ['b'], 'observe': 0},
    ])])
    oracle = result['accepted'][0]
    assert oracle['value'] == ['a', 'b']
    assert oracle['witnesses_checked'] == 1
    assert oracle['uses_pre'] and oracle['uses_arg']
    tape = Tape()
    alias = tape
    tape.put('a')
    alias.put('b')
    assert tape.snapshot() != ast.literal_eval(oracle['literal'])


def test_nesting_toy_transports_expected_structure_and_exposes_interaction():
    def render(value):
        if isinstance(value, list):
            return '[' + value[0] + ']'  # Defect only under the container.
        return value.replace('&', '&amp;')

    assert render('&') == '&amp;'
    assert render(['a']) == '[a]'
    result = validate_completions(completion("'[' + pre[0] + ']'"), [candidate(
        pre=['&amp;'], arg=[], observations=[{'type': 'str'}], witnesses=[
            {'pre': ['a'], 'arg': [], 'after': '[a]'},
        ])])
    assert result['accepted'][0]['value'] == '[&amp;]'
    assert render(['&']) != result['accepted'][0]['value']


def test_set_guard_rejects_duplicate_insert_without_runtime_skip():
    c = candidate(pre=[{'$set': ['a']}], arg=['a'], observations=[{'type': 'int'}])
    payload = completion('len(pre[0]) + 1', 'arg[0] not in pre[0]')
    assert reason(payload, [c]) == 'guard_false'
    c['arg'] = ['b']
    row = validate_completions(payload, [c])['accepted'][0]
    assert row['value'] == 2
    assert 'skip' not in row['literal']


def test_more_precise_set_observation_handles_duplicate_without_guard():
    c = candidate(pre=[{'$set': ['a']}], arg=['a'], observations=[{'type': 'set'}])
    row = validate_completions(completion('pre[0] | {arg[0]}'), [c])['accepted'][0]
    assert decode_value(row['value']) == {'a'}


def test_relation_is_refuted_by_existing_before_after_expectations():
    c = candidate(pre=[1], arg=[], observations=[{'type': 'int'}], witnesses=[
        {'pre': [1], 'arg': [], 'after': 1},
    ])
    assert reason(completion('pre[0] + 1'), [c]) == 'witness_refuted'
    # A bool is not a witnessed int even though Python says True == 1.
    c['witnesses'][0]['after'] = True
    assert reason(completion('pre[0]'), [c]) == 'witness_refuted'


def test_inapplicable_witness_is_reported_and_not_claimed_as_support():
    c = candidate(pre=[{'$set': ['a']}], arg=['b'], observations=[{'type': 'int'}], witnesses=[
        {'pre': [{'$set': ['a']}], 'arg': ['a'], 'after': 1},
    ])
    row = validate_completions(completion('len(pre[0]) + 1', 'arg[0] not in pre[0]'), [c])['accepted'][0]
    assert row['witnesses_checked'] == 0
    assert row['witnesses_inapplicable'] == 1


def test_unknown_source_values_are_explicitly_unsupported_even_for_constant_completion():
    for value in [unknown('call result'), {'$unknown': 'call result'}]:
        c = candidate(pre=[value], observations=[{'type': 'int'}])
        assert reason(completion('42'), [c]) == 'unsupported_source_value'
    assert isinstance(parse_source_literal('run_subject()'), Unknown)


def test_only_program_offered_ids_and_observation_indices_are_accepted():
    assert reason(completion(candidate_id='forged')) == 'unknown_candidate'
    assert reason(completion(observe=True)) == 'observation_index'
    assert reason(completion(observe=-1)) == 'observation_index'
    assert reason(completion(observe=1)) == 'observation_index'
    assert reason({'completions': []}) == 'missing_completion'
    payload = completion()
    payload['completions'].append(dict(payload['completions'][0]))
    assert reason(payload) == 'duplicate_completion'
    assert reason(completion(body='arbitrary code')) == 'completion_schema'


def test_protocol_duplicates_nonfinite_constants_and_markdown_are_rejected():
    assert reason('{"completions": [], "completions": []}') == 'duplicate_key'
    assert reason('{"completions": NaN}') == 'invalid_json'
    assert reason('```json\n{"completions": []}\n```') == 'invalid_json'


@pytest.mark.parametrize('expression', [
    '__import__("os").system("echo wrong")', 'pre[0].append(arg[0])',
    '[x for x in pre[0]]', '(lambda x: x)(pre[0])', 'actual',
    'pre[0].__class__', 'False and __import__("os")',
    'pre[0] if True else dangerous()', 'list(*pre)', '{**pre[0]}',
])
def test_purity_checks_cover_unselected_branches_and_unknown_names(expression):
    with pytest.raises(OracleError) as caught:
        evaluate_expression(expression, [['a']], ['b'])
    assert caught.value.code in {'impure_expression', 'invalid_expression'}


def test_no_user_defined_methods_are_called_while_validating_values():
    class Dangerous:
        def __iter__(self):
            raise AssertionError('Must not run')

        def __str__(self):
            raise AssertionError('Must not run')

    with pytest.raises(OracleError):
        evaluate_expression('str(pre[0])', [Dangerous()])
    with pytest.raises(OracleError):
        evaluate_expression('1', Dangerous())


def test_indices_types_slices_conditionals_and_builtin_calls():
    assert evaluate_expression('tuple(pre[0][1:]) + (arg[0],)', [[1, 2, 3]], [4]) == (2, 3, 4)
    assert evaluate_expression('pre[0][::-1] if len(pre[0]) > 1 else str(arg[0])', ['ab'], [3]) == 'ba'
    for expression, code in [('pre[1]', 'index_error'), ('pre[True]', 'index_type'),
                             ('pre[-1]', 'index_type'), ('pre[0][::0]', 'index_type'),
                             ('pre[0] + 1', 'expression_type')]:
        with pytest.raises(OracleError) as caught:
            evaluate_expression(expression, [['a']])
        assert caught.value.code == code
    assert reason(completion('pre[0]', '1')) == 'guard_type'
    assert reason(completion('1')) == 'observation_type'


def test_complexity_limits_reject_before_large_allocations():
    for expression in ['"a" * 1000000000', '[1] * 1000000000', '10 ** 1000000000', '"%999999999s" % "a"']:
        with pytest.raises(OracleError) as caught:
            evaluate_expression(expression)
        assert caught.value.code in {'value_budget', 'impure_expression'}
    with pytest.raises(OracleError) as caught:
        evaluate_expression('+'.join(['1'] * 40), limits=Limits(expression_nodes=20))
    assert caught.value.code == 'expression_budget'
    cyclic = []
    cyclic.append(cyclic)
    with pytest.raises(OracleError):
        evaluate_expression('pre[0]', [cyclic])


def test_constant_completion_records_absent_dependencies_without_claiming_semantics():
    row = validate_completions(completion('[42]'), [candidate()])['accepted'][0]
    assert not row['uses_pre'] and not row['uses_arg']
    assert row['witnesses_checked'] == 0


def test_json_tags_roundtrip_collision_nonstring_keys_tuple_bytes_and_set():
    value = ({('$tuple', 1): {b'\x00\xff', b'ab'}}, {'$tuple': ['literal key']}, frozenset({1, 2}))
    encoded = json.loads(json.dumps(encode_value(value)))
    assert decode_value(encoded) == value
    for invalid in [{'$tuple': 'abc'}, {'$bytes_hex': 'f'}, {'$set': [1, 1]},
                    {'$mapping': [['x', 1], ['x', 2]]}]:
        with pytest.raises(OracleError):
            decode_value(invalid)


def test_static_source_literals_do_not_run_subject_calls_or_rewrite_strings():
    assert parse_source_literal('("nil", [True, None])') == ('nil', [True, None])
    assert parse_source_literal('{answer: true, word: "null"}', 'typescript') == {'answer': True, 'word': 'null'}
    assert parse_source_literal('[]string{"a", "b",}', 'go') == ['a', 'b']
    assert parse_source_literal('map[string]int{"a": 2}', 'go') == {'a': 2}
    assert parse_source_literal("'a'", 'go') == 97
    assert parse_source_literal('"\\U0001f600"', 'typescript') == 'U0001f600'
    assert parse_source_literal('"\\U0001f600"', 'go') == '😀'
    for code, language in [('load()', 'python'), ('new Set([1])', 'typescript'),
                           ('set()', 'python'), ('undefined', 'typescript'),
                           ('True', 'typescript'), ('None', 'go')]:
        assert isinstance(parse_source_literal(code, language), Unknown)


def test_python_literal_emission_preserves_values_and_escape_sequences():
    value = ('quotes\'"\\\n\x00😀\ud800', {'x': [True, None, -3.25]}, b'\x00\xff')
    assert ast.literal_eval(emit_literal(value, 'python')) == value


def test_python_set_literals_and_completion_cache_are_stable_across_hash_seeds():
    script = r'''
import json
from prototypes.test_action_and_oracle_transfer.oracle import encode_value, emit_literal, same_value, validate_completions
value = {
    'z_last_alphabetically': [
        {'indigo', 'amber', 'violet', 'cyan'},
        (frozenset({'one', 'two', 'three'}),),
        set(),
        frozenset(),
    ],
    'a_first_alphabetically': {
        frozenset({'orange', 'green'}),
        frozenset({frozenset({'left', 'right'}), frozenset({'top', 'bottom'})}),
        ('tuple', frozenset({b'bytes', 'text', 7, None})),
    },
}
literal = emit_literal(value, 'python')
restored = eval(literal, {'__builtins__': {}}, {'set': set, 'frozenset': frozenset})
assert same_value(value, restored)
assert list(restored) == ['z_last_alphabetically', 'a_first_alphabetically']
assert type(restored['z_last_alphabetically'][1]) is tuple
assert type(restored['z_last_alphabetically'][1][0]) is frozenset
assert type(restored['z_last_alphabetically'][2]) is set
assert type(restored['z_last_alphabetically'][3]) is frozenset
candidate = {'candidate_id': 'c0', 'language': 'python', 'pre': [encode_value(value)],
             'arg': [], 'observations': [{'type': 'dict'}]}
payload = {'completions': [{'candidate_id': 'c0', 'observe': 0, 'expected': 'pre[0]', 'guard': None}]}
accepted = validate_completions(payload, [candidate])['accepted'][0]
assert accepted['literal'] == literal
print(json.dumps({'literal': literal, 'wire': encode_value(value), 'accepted': accepted}, ensure_ascii=True))
'''
    outputs = []
    for seed in ['0', '1', '2', '13', '47', 'random']:
        run = subprocess.run([sys.executable, '-c', script], text=True, capture_output=True,
                             env=dict(os.environ, PYTHONHASHSEED=seed),
                             cwd=Path(__file__).resolve().parents[1], check=True, timeout=10)
        outputs.append(run.stdout)
    assert len(set(outputs)) == 1


@pytest.mark.parametrize('expression,value', [
    ('list(pre[0])', {'alpha', 'beta'}),
    ('tuple(pre[0])', frozenset({'alpha', 'beta'})),
    ('list(pre[0])', set()),
    ('str(pre[0])', {'alpha', 'beta'}),
    ('str(pre[0])', [{'nested': (frozenset({'alpha', 'beta'}),)}]),
    ('str(pre[0])', {frozenset({'alpha', 'beta'}): 'set used as a key'}),
    ('str([pre[0]])', {'alpha', 'beta'}),
])
def test_order_sensitive_set_conversions_are_rejected_without_inventing_an_order(expression, value):
    with pytest.raises(OracleError) as caught:
        evaluate_expression(expression, [value])
    assert caught.value.code == 'unordered_conversion'


def test_unordered_values_may_remain_inside_ordered_containers_without_conversion():
    value = [{'alpha', 'beta'}, frozenset({'gamma', 'delta'})]
    result = evaluate_expression('tuple(pre[0])', [value])
    assert type(result) is tuple
    assert type(result[0]) is set and type(result[1]) is frozenset
    assert result == tuple(value)
    assert evaluate_expression('list(pre[0])', [{'z': 1, 'a': 2}]) == ['z', 'a']
    assert evaluate_expression('str(pre[0])', [{'z': [1, 2], 'a': 3}]) == "{'z': [1, 2], 'a': 3}"


def test_go_container_types_are_explicit_when_ambiguous_and_range_checked():
    assert emit_literal(['a', 'b'], 'go') == '[]string{"a", "b"}'
    assert emit_literal([], 'go', '[]string') == '[]string{}'
    assert emit_literal({'x': [1]}, 'go', 'map[string][]int') == 'map[string][]int{"x": []int{1}}'
    assert emit_literal(None, 'go', 'map[string]int') == 'nil'
    for value, hint in [([], None), ([1, 'x'], None), ((1, 2), None),
                        ([1], '[]string'), ([1], '[2]int'), (256, 'uint8'), (True, 'int'),
                        (10 ** 1000, 'float64'), (2 ** 53 + 1, 'float64'), (0.1, 'float32')]:
        with pytest.raises(OracleError):
            emit_literal(value, 'go', hint)


def test_typescript_literals_preserve_proto_and_reject_numeric_precision_loss():
    assert '["__proto__"]' in emit_literal({'__proto__': {'ok': True}}, 'typescript')
    with pytest.raises(OracleError):
        emit_literal(2 ** 53 + 1, 'typescript')
    with pytest.raises(OracleError):
        emit_literal({1: 'x'}, 'typescript')
    with pytest.raises(OracleError):
        emit_literal(float('nan'), 'python')


@pytest.mark.skipif(shutil.which('node') is None, reason='Node is unavailable')
def test_emitted_typescript_compatible_literals_execute_with_exact_contents():
    value = {'__proto__': 'data', 'quotes': "'\"\\\n\u2028\u2029😀\ud800", 'values': [None, True, 3]}
    expression = emit_literal(value, 'typescript')
    result = subprocess.run(['node', '-e', 'const x = ' + expression + '; process.stdout.write(JSON.stringify(x));'],
                            text=True, capture_output=True, check=True, timeout=10)
    assert json.loads(result.stdout) == value


@pytest.mark.skipif(shutil.which('go') is None, reason='Go is unavailable')
def test_emitted_go_literals_compile_with_exact_contents(tmp_path):
    value = ['a\n"\\', '😀', '\u2028\u2029', '\x00']
    literal = emit_literal(value, 'go', '[]string')
    code = 'package main\nimport ("encoding/json"; "os")\nfunc main() { json.NewEncoder(os.Stdout).Encode(' + literal + ') }\n'
    path = tmp_path / 'main.go'
    path.write_text(code)
    result = subprocess.run(['go', 'run', str(path)], text=True, capture_output=True, timeout=45)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == value
