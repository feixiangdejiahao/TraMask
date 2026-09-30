"""Source fidelity and an isolated native Go toy; no real task execution."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

from anchor_retrieval.syntax import Source, child
from experimental.go_comparison_probe import TRACE_ENV, instrument_sources, read_trace


def source(code, path='toy.go'):
    return Source(path, code, 'go')


def selection(src, name='check'):
    nodes = [node for node in src.root.named_children
             if node.type in {'function_declaration', 'method_declaration'}
             and src.text(child(node, 'name')) == name]
    assert len(nodes) == 1
    return dict(path=src.path, start_byte=nodes[0].start_byte, end_byte=nodes[0].end_byte,
                source_sha256=hashlib.sha256(src.data).hexdigest())


def instrument(code, name='check', extra=()):
    src = source(code)
    return instrument_sources([src, *extra], [selection(src, name)])


def reasons(result):
    return {row['reason'] for row in result['unknowns']}


def test_grouped_parameters_local_types_and_all_comparators():
    result = instrument('''package toy
func check(a, b int, u uint64) bool {
    x := a + b
    var y int = 7
    const k = 4
    if x < b && y <= a && a == b && a != b && u >= k && u > 0 {return true}
    return false
}
''')
    assert len(result['comparisons']) == 6
    assert not result['unknowns']
    assert [row['operator'] for row in result['comparisons']] == ['<', '<=', '==', '!=', '>=', '>']
    assert [row['primitive_type'] for row in result['comparisons']] == ['int'] * 4 + ['uint64'] * 2


def test_only_selected_functions_and_if_conditions():
    src = source('''package toy
func other(x int) {if x < 1 {}}
func check(x int) {ok := x < 1; _ = ok; for x < 2 {break}; if x > 0 {}}
''')
    result = instrument_sources([src], [selection(src), selection(src)])
    assert [row['before'] for row in result['comparisons']] == ['x > 0']
    assert result['files'][src.path].count('if x < 1') == 1


def test_unique_same_package_return_type_with_opaque_integer_body():
    callee = source('''package toy
func opaque(x string) int {return len(x)}
''', 'production.go')
    result = instrument('''package toy
func check(limit int) bool {if opaque("data") >= limit {return true}; return false}
''', extra=[callee])
    assert len(result['comparisons']) == 1
    row = result['comparisons'][0]
    assert row['primitive_type'] == 'int'
    assert row['calls'][0]['callee_span']['path'] == callee.path
    assert row['calls'][0]['result_type'] == 'int'
    assert row['runtime_status'] == 'unobserved'
    assert result['files'][callee.path] == callee.code


def test_two_source_calls_and_named_integer_result():
    result = instrument('''package toy
func first() (r int) {return 2}
func second() int {return 3}
func check() bool {if first() < second() {return true};return false}
''')
    assert len(result['comparisons']) == 1
    assert len(result['comparisons'][0]['calls']) == 2
    assert result['comparisons'][0]['after'].count('first()') == 1
    assert result['comparisons'][0]['after'].count('second()') == 1


def test_nested_comparisons_keep_innermost_and_do_not_abort_source_census():
    result = instrument('''package toy
func boolToInt(x bool) int {if x {return 1}; return 0}
func check(x int) {if boolToInt(x < 1) < 3 {}}
''')
    assert [row['before'] for row in result['comparisons']] == ['x < 1']
    assert reasons(result) == {'nested_comparison_rewrite_overlap'}
    assert 'boolToInt(' in result['files']['toy.go']
    assert '< 3' in result['files']['toy.go']


def test_closure_body_inside_condition_never_reuses_outer_lexical_scope():
    result = instrument('''package toy
func check(x int) {if func() bool {x := "a"; return x < "b"}() {}}
''')
    assert not result['comparisons']
    assert result['files']['toy.go'].count('x < "b"') == 1


def test_if_initializer_and_nested_block_shadow_do_not_leak():
    result = instrument('''package toy
func check(a int, b uint64) {
    if a := b; a > 0 {}
    {a := b; if a > 0 {}}
    if a > 0 {}
}
''')
    assert [row['primitive_type'] for row in result['comparisons']] == ['uint64', 'uint64', 'int']


def test_grouped_var_initializers_use_pre_declaration_environment():
    result = instrument('''package toy
func check(a uint64) { {var a, b = 1, a; if b > 0 {}; _=a} }
''')
    assert [row['primitive_type'] for row in result['comparisons']] == ['uint64']


@pytest.mark.parametrize('definition,parameters,condition', [
    ('type Count int', 'x Count', 'x < 1'),
    ('', 'x float64', 'x < 1'),
    ('', 'x bool', 'x == true'),
    ('', 'x string', 'x == "a"'),
    ('', 'x *int', '*x < 1'),
    ('func f() (int, int) {return 1,2}', 'x int', 'f() < x'),
    ('func f() float64 {return 1}', 'x int', 'f() < x'),
    ('type Box struct{}; func (b Box) f() int {return 1}', 'x int, b Box', 'b.f() < x'),
])
def test_unsupported_operand_types_or_dispatch_are_explicit_unknown(definition, parameters, condition):
    result = instrument('package toy\n' + definition + '\nfunc check(' + parameters + ') {if ' + condition + ' {}}')
    assert not result['comparisons']
    assert len(result['unknowns']) == 1
    assert not result['runtime_files']


@pytest.mark.parametrize('body,reason', [
    ('p := &x; _=p; if f() < x {}', 'call_can_observe_or_change_escaped_scalar'),
    ('g := func(){_ = x}; _=g; if f() < x {}', 'call_can_observe_or_change_escaped_scalar'),
    ('go f(); if f() < x {}', 'concurrent_function_scope_unsupported'),
    ('f := func() int{return 1}; if f() < x {}', 'callee_binding_not_static'),
    ('if f() < x / 2 {}', 'panic_and_call_evaluation_order_unknown'),
])
def test_effect_order_and_lexical_binding_boundaries(body, reason):
    result = instrument('package toy\nfunc f() int {return 2}\nfunc check(x int) {' + body + '}')
    assert not result['comparisons']
    assert reason in reasons(result)


def test_local_type_shadow_and_range_binding_are_not_numeric_proof():
    result = instrument('''package toy
func check(x int, values []string) {
    {type int = string; var y int = "text"; if y == "text" {}}
    for _, x := range values {if x < "a" {}}
    if x > 0 {}
}
''')
    assert [row['before'] for row in result['comparisons']] == ['x > 0']
    assert len(result['unknowns']) == 2


def test_duplicate_function_or_other_directory_not_a_unique_local_callee():
    caller = source('package toy\nfunc check(x int) {if f() < x {}}')
    first = source('package toy\nfunc f() int {return 1}', 'a.go')
    second = source('package toy\nfunc f() int {return 2}', 'b.go')
    result = instrument_sources([caller, first, second], [selection(caller)])
    assert 'callee_declaration_not_unique' in reasons(result)
    other_dir = source(first.code, 'other/a.go')
    result = instrument_sources([caller, other_dir], [selection(caller)])
    assert 'callee_declaration_not_unique' in reasons(result)


def test_selected_source_span_and_sha_must_match():
    src = source('package toy\nfunc check(x int) {if x < 1 {}}')
    extent = selection(src)
    bad_sha = dict(extent, source_sha256='0' * 64)
    bad_span = dict(extent, end_byte=extent['end_byte'] - 1)
    unavailable = dict(extent, path='missing.go')
    result = instrument_sources([src], [bad_sha, bad_span, unavailable])
    assert reasons(result) == {'selected_source_sha_mismatch', 'selected_function_span_not_unique_declaration', 'selected_source_unavailable'}
    assert result['files'][src.path] == src.code


def test_selected_external_declaration_without_body_is_explicit_unknown():
    src = source('package toy\nfunc check(x int) int\n')
    result = instrument_sources([src], [selection(src)])
    assert reasons(result) == {'selected_function_body_unavailable'}
    assert result['files'][src.path] == src.code


def test_utf8_multiline_spans_roundtrip_and_deterministic_identity():
    src = source('''package toy
// 中文 UTF-8 before source coordinates
func check(x, y int) {
    if (x +
        1) < y {}
    if y == 3 {}
}
''')
    extra = source('package toy\nfunc untouched() {}', 'extra.go')
    result = instrument_sources([src, extra], [selection(src)])
    reverse = instrument_sources([extra, src], [selection(src)])
    assert result == reverse
    data = result['files'][src.path].encode()
    original = src.data
    for row in reversed(result['comparisons']):
        before, after = row['original_span'], row['modified_span']
        assert original[before['start_byte']:before['end_byte']].decode() == row['before']
        assert data[after['start_byte']:after['end_byte']].decode() == row['after']
        data = data[:after['start_byte']] + row['before'].encode() + data[after['end_byte']:]
    assert data == original
    assert src.data == original
    assert extra.code == result['files'][extra.path]


def test_trace_reader_never_turns_missing_or_invalid_events_into_relations(tmp_path):
    result = instrument('package toy\nfunc check(x int) {if x < 1 {}; if x > 3 {}}')
    rows = result['comparisons']
    path = tmp_path / 'trace.jsonl'
    assert read_trace(path, rows)['status'] == 'unknown'
    path.write_text(json.dumps(dict(id=rows[0]['id'], operator='<', relation='=')) + '\n')
    trace = read_trace(path, rows)
    assert trace['status'] == 'partial'
    assert trace['missing_ids'] == [rows[1]['id']]
    path.write_text(path.read_text() + '{not json}\n' + json.dumps(dict(id=rows[1]['id'], operator='<', relation='>')) + '\n')
    trace = read_trace(path, rows)
    assert trace['status'] == 'unknown'
    assert len(trace['events']) == 1
    assert len(trace['errors']) == 2
    assert trace['missing_ids'] == [rows[1]['id']]


def _go_environment(tmp_path):
    return dict(os.environ, GOTOOLCHAIN='local', GOPROXY='off', GOSUMDB='off',
                GO111MODULE='off', GOCACHE=str(tmp_path / 'go-cache'), GOMODCACHE=str(tmp_path / 'go-mod-cache'))


@pytest.mark.skipif(shutil.which('go') is None, reason='local Go unavailable')
def test_native_toy_preserves_original_calls_order_short_circuit_and_output(tmp_path):
    src = source('''package main
import "fmt"
var order string
var counts [3]int
func left() int {order += "L"; counts[0]++; return 2}
func right() int {order += "R"; counts[1]++; return 3}
func later() int {order += "X"; counts[2]++; return 9}
func check(bound int) bool {
    if left() < right() && later() > bound {return true}
    return false
}
func stopped(bound int) bool {
    if left() > right() && later() > bound {return true}
    return false
}
func main() {fmt.Println(check(4), stopped(4), order, counts)}
''', 'main.go')
    result = instrument_sources([src], [selection(src), selection(src, 'stopped')])
    original_dir, modified_dir = tmp_path / 'original', tmp_path / 'instrumented'
    original_dir.mkdir(); modified_dir.mkdir()
    (original_dir / src.path).write_text(src.code)
    for name, code in {**result['files'], **result['runtime_files']}.items():
        assert not Path(name).name.startswith(('_', '.'))
        (modified_dir / name).write_text(code)
    env = _go_environment(tmp_path)
    original = subprocess.run(['go', 'run', '.'], cwd=original_dir, env=env, capture_output=True, text=True, check=True, timeout=120)
    trace_path = tmp_path / 'trace.jsonl'
    instrumented = subprocess.run(['go', 'run', '.'], cwd=modified_dir, env=dict(env, **{TRACE_ENV: str(trace_path)}), capture_output=True, text=True, check=True, timeout=120)
    assert instrumented.stdout == original.stdout == 'true false LRXLR [2 2 1]\n'
    assert instrumented.stderr == original.stderr == ''
    trace = read_trace(trace_path, result['comparisons'])
    assert trace['status'] == 'partial'
    assert [event['relation'] for event in trace['events']] == ['<', '>', '<']
    assert len(trace['missing_ids']) == 1  # later() in the false left && was never executed.
    bad_logger = subprocess.run(['go', 'run', '.'], cwd=modified_dir, env=dict(env, **{TRACE_ENV: str(tmp_path)}), capture_output=True, text=True, check=True, timeout=120)
    assert bad_logger.stdout == original.stdout
    assert bad_logger.stderr == ''


@pytest.mark.skipif(shutil.which('go') is None, reason='local Go unavailable')
def test_native_integer_relations_signed_unsigned_and_original_boolean_results(tmp_path):
    src = source('''package main
import "fmt"
func check(a, b int, u uint64) bool {
    if a < b {} else {return false}
    if a == a {} else {return false}
    if b > a {} else {return false}
    if u >= 0 {} else {return false}
    if a != b {} else {return false}
    if a <= b {} else {return false}
    return true
}
func main() {fmt.Println(check(-2, 3, 7))}
''', 'main.go')
    result = instrument_sources([src], [selection(src)])
    for name, code in {**result['files'], **result['runtime_files']}.items():
        (tmp_path / name).write_text(code)
    trace_path = tmp_path / 'trace.jsonl'
    run = subprocess.run(['go', 'run', '.'], cwd=tmp_path,
                         env=dict(_go_environment(tmp_path), **{TRACE_ENV: str(trace_path)}),
                         capture_output=True, text=True, check=True, timeout=120)
    assert run.stdout == 'true\n'
    trace = read_trace(trace_path, result['comparisons'])
    assert trace['status'] == 'observed'
    assert [event['relation'] for event in trace['events']] == ['<', '=', '>', '>', '<', '<']
