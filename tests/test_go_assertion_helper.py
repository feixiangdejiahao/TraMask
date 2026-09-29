import copy

import pytest

from anchor_retrieval.syntax import Source, child, walk
from experimental.go_assertion_helper import HelperIndex, summarize_helper


def summarize(code, name='check'):
    source = Source('pkg/test_test.go', code, 'go')
    assert not source.root.has_error
    function = next(item for item in source.root.named_children
                    if item.type == 'function_declaration' and source.text(child(item, 'name')) == name)
    return summarize_helper(source, function)


def helper(body, parameters='t *testing.T, box *Box, desired string', imports='"testing"'):
    return f'package sample\nimport ({imports})\ntype Box struct{{ value string }}\nfunc check({parameters}){{{body}}}\n'


@pytest.mark.parametrize('name,parameters,body,expected_index', [
    ('check', 't *testing.T, box *Box, desired string',
     'if box.value != desired { t.Errorf("bad %s", desired) }', 2),
    ('totallyRenamed', 'w string, x *testing.T, z *Box',
     'if w != z.value { x.Errorf("bad %s", w) }', 0),
    ('compare', 'z *Box, w string, x *testing.T',
     'v := z.value; if w != v { x.Error(w, v) }', 1),
])
def test_role_follows_dependency_not_names_or_parameter_order(name, parameters, body, expected_index):
    code = helper(body, parameters).replace('func check(', f'func {name}(')
    result = summarize(code, name)
    assert result['status'] == 'supported', result
    assert result['expected_parameter_index'] == expected_index
    assert len(result['actual_parameter_indices']) == 1
    assert result['actual_parameter_indices'][0] != expected_index


def test_testing_import_alias_and_prerequisite_error_guards_remain_explicit():
    code = '''package sample
import (testlib "testing"; "strings")
type Box struct { value string }
func check(t *testlib.T, box *Box, desired string) {
 t.Helper()
 handle := box.value
 if _, err := seek(handle); err != nil { t.Fatal(err) }
 bytes, err := read(handle)
 if err != nil { t.Fatal(err) }
 if string(bytes) != desired {
  desired = strings.ReplaceAll(desired, "a", "b")
  t.Errorf("bad %s", desired)
 }
 cleanup(handle)
}
'''
    result = summarize(code)
    assert result['status'] == 'supported', result
    assert result['actual_parameter_dependencies'] == ['box']
    assert len(result['prerequisite_guards']) == 2
    assert all(row['failure_methods'] == ['Fatal'] for row in result['prerequisite_guards'])
    assert result['known_pure_diagnostic_calls'][0]['expression'].startswith('strings.ReplaceAll')
    assert [row['expression'] for row in result['local_definitions'] if row['name'] == 'bytes'] == ['read(handle)']


def test_direct_formal_pair_is_symmetric_despite_expected_looking_name():
    result = summarize(helper('if got != expected {t.Error(got, expected)}',
                              't *testing.T, got string, expected string'))
    assert result['reason'] == 'symmetric_parameter_comparison'


def test_expected_flow_into_actual_is_not_a_separable_slot():
    result = summarize(helper('got := combine(box.value, desired); if got != desired {t.Error(got)}'))
    assert result['reason'] == 'expected_also_flows_to_actual'


@pytest.mark.parametrize('body', [
    'consume(desired); if box.value != desired {t.Error("bad")}',
    'if box.value != desired {t.Error(formatUnknown(desired))}',
    'if box.value != desired {consume(desired); t.Error("bad")}',
    'if box.value != desired {t.Error("bad")}; consume(desired)',
])
def test_opaque_expected_consumption_is_unknown(body):
    result = summarize(helper(body))
    assert result['reason'] == 'expected_consumed_by_opaque_or_nondiagnostic_call'


def test_same_spelling_with_wrong_import_is_not_known_pure():
    result = summarize(helper('if box.value != desired { t.Error(strings.ReplaceAll(desired,"a","b")) }',
                             imports='"testing"; strings "example.org/custom"'))
    assert result['reason'] == 'expected_consumed_by_opaque_or_nondiagnostic_call'


def test_shadowed_standard_library_alias_is_not_known_pure():
    result = summarize(helper('strings := fake(); if box.value != desired {t.Error(strings.ReplaceAll(desired,"a","b"))}',
                             imports='"testing"; "strings"'))
    assert result['reason'] == 'expected_consumed_by_opaque_or_nondiagnostic_call'


def test_package_variable_shadowing_builtin_is_not_known_pure():
    code = helper('if box.value != desired { t.Error(len(desired)) }')
    code += 'var len = func(s string) int { return consume(s) }'
    assert summarize(code)['reason'] == 'expected_consumed_by_opaque_or_nondiagnostic_call'


def test_multiple_data_assertions_are_not_collapsed():
    result = summarize(helper('if box.value != desired {t.Error("one")}; if len(box.value) != width {t.Error("two")}',
                             't *testing.T, box *Box, desired string, width int'))
    assert result['reason'] == 'requires_unique_parameter_comparison'
    assert result['count'] == 2


@pytest.mark.parametrize('body,reason', [
    ('if box.value != desired {t.Error("bad")}; if other() {t.Fail()}', 'additional_failure_comparison'),
    ('for i:=0;i<2;i++ {if box.value != desired {t.Error("bad")}}', 'unsupported_control_flow'),
    ('desired = "changed"; if box.value != desired {t.Error("bad")}', 'expected_reassigned_before_comparison'),
    ('err := read(box.value); if err != nil {t.Error(err)}; if box.value != desired {t.Error("bad")}', 'unsupported_prerequisite_guard'),
    ('if box.value != desired {other.value=desired; t.Error("bad")}', 'nonlocal_assignment'),
    ('if box.value != desired {t.Error("bad")}; t.Fail()', 'failure_report_outside_recognized_guards'),
])
def test_unsupported_shapes_remain_unknown(body, reason):
    assert summarize(helper(body))['reason'] == reason


def test_callsite_span_is_only_expected_argument_and_inputs_are_immutable():
    code = helper('if box.value != desired {t.Error("bad")}',
                  'desired string, box *Box, t *testing.T')
    code += 'func TestExample(t *testing.T){ box:=&Box{}; check("旧值",box,t) }'
    data = {'language': 'go', 'sources': {'pkg/test_test.go': {'code': code, 'language': 'go'}}}
    frozen = copy.deepcopy(data)
    index = HelperIndex(data)
    source = index.arity.sources['pkg/test_test.go']
    call = next(node for node in walk(source.root)
                if node.type == 'call_expression' and source.text(child(node, 'function')) == 'check')
    result = index.call(source, call)
    assert result['status'] == 'supported', result
    assert result['expected_argument_index'] == 0
    extent = result['expected_argument_span']
    edited = source.data[:extent['start_byte']] + b'"new"' + source.data[extent['end_byte']:]
    assert edited.decode() == code.replace('check("旧值",box,t)', 'check("new",box,t)')
    assert result['unchanged_callee']['text'] == 'check'
    assert [row['text'] for row in result['unchanged_arguments']] == ['box', 't']
    assert data == frozen


def test_duplicate_same_package_helper_declarations_are_ambiguous():
    code = helper('if box.value != desired {t.Error("bad")}')
    code += 'func TestExample(t *testing.T){ check(t,&Box{},"old") }'
    data = {'language': 'go', 'sources': {
        'pkg/a_test.go': {'code': code, 'language': 'go'},
        'pkg/b_test.go': {'code': helper('if box.value != desired {t.Error("bad")}'), 'language': 'go'}}}
    index = HelperIndex(data)
    source = index.arity.sources['pkg/a_test.go']
    call = next(node for node in walk(source.root)
                if node.type == 'call_expression' and source.text(child(node, 'function')) == 'check')
    assert index.call(source, call)['reason'] == 'ambiguous_declaration'


def test_local_callee_shadow_does_not_use_package_helper_summary():
    code = helper('if box.value != desired {t.Error("bad")}')
    code += 'func TestExample(t *testing.T){check:=unknown();check(t,&Box{},"old")}'
    data = {'language': 'go', 'sources': {'pkg/a_test.go': {'code': code, 'language': 'go'}}}
    index = HelperIndex(data)
    source = index.arity.sources['pkg/a_test.go']
    call = next(node for node in walk(source.root)
                if node.type == 'call_expression' and source.text(child(node, 'function')) == 'check')
    assert index.call(source, call)['reason'] == 'unresolved_local_function_binding'


@pytest.mark.parametrize('parameters', ['t *testing.T, rest ...string', '*testing.T, string'])
def test_unsupported_helper_parameters_still_enter_census_denominator(parameters):
    code = f'package sample\nimport "testing"\nfunc check({parameters}){{}}\nfunc TestExample(t *testing.T){{check(t,"x")}}'
    source = Source('pkg/a_test.go', code, 'go')
    test = next(node for node in source.root.named_children if node.type == 'function_declaration'
                and source.text(child(node, 'name')) == 'TestExample')
    data = {'language': 'go', 'sources': {source.path: {'code': code, 'language': 'go'}},
            'tests': {'test': {'body_span': {'path': source.path,
             'start_byte': test.start_byte, 'end_byte': test.end_byte}, 'owner_kind': 'registered_test'}}}
    result = HelperIndex(data).census()
    assert result['counts']['same_package_testing_helper_name_calls'] == 1
    assert result['counts']['unknown'] == 1
    assert result['records'][0]['reason'] == 'requires_one_testing_T_parameter'
