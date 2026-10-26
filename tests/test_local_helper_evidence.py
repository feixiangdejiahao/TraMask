import copy

import pytest

from anchor_retrieval.syntax import Source
from prototypes.local_helper_evidence import _writes, analyze
from anchor_retrieval.syntax import walk
from relational_gap.frontend import extract_frontend, to_emitter_corpus
from relation_search.oracle_evidence import _modified_sources


PROGRAMS = {
    'go': ('local_test.go', '''package local
import "testing"
import "github.com/stretchr/testify/require"
func TestLocal(t *testing.T) {
    // 原始源码 contains UTF-8.
    check := func(x int, z int) {
        actual := x * 2
        require.Equal(t, z, actual)
    }
    check(2,4)
    check(3,6)
}
'''),
    'python': ('test_local.py', '''def test_local():
    # 原始源码 contains UTF-8.
    def check(x, z):
        actual = x * 2
        assert actual == z
    check(2,4)
    check(3,6)
'''),
    'typescript': ('local.test.ts', '''import { test, expect } from 'vitest';
test('local', () => {
    // 原始源码 contains UTF-8.
    const check = (x: number, z: number) => {
        const actual = x * 2;
        expect(actual).toBe(z);
    };
    check(2,4);
    check(3,6);
});
'''),
}


def fixture(language, replace=None):
    path, code = PROGRAMS[language]
    if replace:
        for before, after in replace:
            code = code.replace(before, after)
    front = extract_frontend([Source(path, code, language)])
    corpus = to_emitter_corpus(front)
    base = next(iter(corpus['tests']))
    return corpus, dict(id='candidate', base_test_id=base, edits=[])


def at(source, extent):
    return source.data[extent['start_byte']:extent['end_byte']].decode()


@pytest.mark.parametrize('language', list(PROGRAMS))
def test_each_call_has_independent_formal_bindings_and_expected_argument(language):
    corpus, candidate = fixture(language)
    original = copy.deepcopy(candidate)
    result = analyze(corpus, candidate)
    assert candidate == original
    assert result['counts']['resolved_calls'] == 2
    assert result['counts']['expected_argument_ports'] == 2
    first, second = result['calls']
    assert first['id'] != second['id'] and first['binding_id'] == second['binding_id']
    assert [row['actual']['code'] for row in first['actual_formal']] == ['2','4']
    assert [row['actual']['code'] for row in second['actual_formal']] == ['3','6']
    assert [row['assertions'][0]['expected_argument']['code'] for row in result['calls']] == ['4','6']
    assert first['assertions'][0]['observed_formal_dependencies'] == ['x']
    _, current, *_ = _modified_sources(corpus, candidate)
    for call in result['calls']:
        assert at(current, call['span']) == call['code']
        for binding in call['actual_formal']:
            assert at(current, binding['actual']['span']) == binding['actual']['code']
        assertion, = call['assertions']
        assert assertion['call_span'] == call['span']
        assert at(current, assertion['expected_argument']['span']) == assertion['expected_argument']['code']
        assert at(current, assertion['observed']['span']) == 'actual'


def test_roles_come_from_assertion_operands_not_names_or_parameter_positions():
    corpus, candidate = fixture('go', [('check','mystery'), ('x int, z int','z int, x int'),
        ('mystery(2,4)','mystery(4,2)'), ('mystery(3,6)','mystery(6,3)')])
    result = analyze(corpus, candidate)
    assert result['calls'][0]['actual_formal'][0]['formal']['name'] == 'z'
    assert result['calls'][0]['assertions'][0]['expected_argument']['code'] == '4'
    assert result['calls'][0]['assertions'][0]['observed_argument_bindings'][0]['actual']['code'] == '2'


@pytest.mark.parametrize('language', list(PROGRAMS))
def test_modified_source_reparsing_preserves_exact_utf8_argument_locations(language):
    corpus, candidate = fixture(language)
    owner = corpus['tests'][candidate['base_test_id']]['span']
    data = corpus['sources'][owner['path']]['code'].encode()
    begin = data.index(b'check(2,4)')+len(b'check(')
    candidate['edits'] = [dict(span=dict(path=owner['path'],start_byte=begin,end_byte=begin+1),
                               before='2',after='10001',role='input')]
    result = analyze(corpus, candidate)
    assert result['calls'][0]['actual_formal'][0]['actual']['code'] == '10001'
    assert result['calls'][0]['assertions'][0]['expected_argument']['code'] == '4'
    _, current, *_ = _modified_sources(corpus, candidate)
    assert at(current,result['calls'][1]['actual_formal'][1]['actual']['span']) == '6'
    assert result['source_scope']['end_byte'] == owner['end_byte']+4


@pytest.mark.parametrize('language,replace,reason', [
    ('go',[('check(2,4)','check(2)')],'argument_arity_mismatch'),
    ('go',[('check(2,4)','check(values...)')],'spread_or_keyword_arguments'),
    ('python',[('check(2,4)','check(*values)')],'spread_or_keyword_arguments'),
    ('python',[('check(2,4)','check(x=2, z=4)')],'spread_or_keyword_arguments'),
    ('typescript',[('check(2,4)','check(...values)')],'spread_or_keyword_arguments'),
    ('python',[('def check(x, z):','def check(x, z=4):')],'unsupported_parameters'),
    ('typescript',[('z: number)','z: number = 4)')],'unsupported_parameters'),
    ('go',[('z int)','z ...int)')],'unsupported_parameters'),
])
def test_unsupported_call_or_parameter_shapes_remain_unknown(language, replace, reason):
    corpus, candidate = fixture(language, replace)
    result = analyze(corpus,candidate)
    assert result['calls'][0]['status'] == 'unknown'
    assert result['calls'][0]['reason'] == reason
    assert result['calls'][0]['actual_formal'] == [] and result['calls'][0]['assertions'] == []


@pytest.mark.parametrize('language,replace', [
    ('go',[('check(2,4)','check = other\n    check(2,4)')]),
    ('python',[('    check(2,4)','    check = other\n    check(2,4)')]),
    ('typescript',[('check(2,4)','check = other; check(2,4)')]),
])
def test_reassigned_helper_is_not_resolved_by_its_spelling(language, replace):
    corpus, candidate = fixture(language,replace)
    result = analyze(corpus,candidate)
    assert all(row['status']=='unknown' and row['reason']=='helper_reassigned_or_shadowed' for row in result['calls'])


def test_branch_shadow_and_block_scope_are_unknown_instead_of_borrowing_outer_name():
    corpus, candidate = fixture('typescript',[('    check(2,4);',
        '    if (flag) { const check = other; check(2,4); }')])
    result = analyze(corpus,candidate)
    assert all(row['status']=='unknown' for row in result['calls'])
    corpus, candidate = fixture('typescript',[('    const check =','    { const check ='),
        ('    check(2,4);','    } check(2,4);')])
    result = analyze(corpus,candidate)
    assert all(row['reason']=='local_helper_binding_ambiguous_or_different_scope' for row in result['calls'])


def test_formal_assignment_is_unknown_and_other_uses_prevent_expected_port_transport():
    corpus, candidate = fixture('python',[('        actual = x * 2','        z = 4\n        actual = x * 2')])
    result = analyze(corpus,candidate)
    assert all(row['reason']=='formal_reassigned_or_shadowed' for row in result['calls'])
    corpus, candidate = fixture('go',[('actual := x * 2','actual := x * z')])
    result = analyze(corpus,candidate)
    assert all(row['status']=='resolved' for row in result['calls'])
    assert all(row['assertions'][0]['expected_argument'] is None for row in result['calls'])
    assert result['calls'][0]['assertions'][0]['expected_port_reason']=='expected_formal_has_other_uses'


def test_custom_require_package_does_not_establish_an_expected_role():
    corpus,candidate = fixture('go',[('github.com/stretchr/testify/require','example.com/custom/require')])
    result = analyze(corpus,candidate)
    assert result['counts']['expected_argument_ports']==0
    assert all(row['assertions'][0]['expected_port_reason']=='assertion_adapter_import_unproved' for row in result['calls'])


@pytest.mark.parametrize('language,replace', [
    ('go', [('    check := func', '    require := custom\n    check := func')]),
    ('go', [('    check(2,4)', '    require = custom\n    check(2,4)')]),
    ('typescript', [('    const check =', '    const expect = custom;\n    const check =')]),
    ('typescript', [('    check(2,4);', '    expect = custom;\n    check(2,4);')]),
])
def test_outer_framework_receiver_shadow_or_write_denies_expected_port(language, replace):
    corpus, candidate = fixture(language, replace)
    result = analyze(corpus, candidate)
    assert result['counts']['resolved_calls'] == 2
    assert result['counts']['expected_argument_ports'] == 0
    assert all(row['assertions'][0]['expected_port_reason'] == 'assertion_adapter_rebound'
               for row in result['calls'])


@pytest.mark.parametrize('declaration',[
    'var a, require = 1, custom',
    'for _, require := range custom { _=require }',
    'type require = Custom',
    'const require = 1',
])
def test_go_all_declaration_names_conservatively_deny_framework_receiver_port(declaration):
    corpus,candidate=fixture('go',[('    check := func','    '+declaration+'\n    check := func')])
    result=analyze(corpus,candidate)
    assert result['counts']['resolved_calls']==2
    assert result['counts']['expected_argument_ports']==0
    assert all(row['assertions'][0]['expected_port_reason']=='assertion_adapter_rebound' for row in result['calls'])


def test_go_grouped_const_and_var_declared_names_do_not_drop_second_binding():
    source=Source('names.go','package p\nfunc f(){var a,b=1,2;const c,d=3,4}\n','go')
    rows=[_writes(source,node) for node in walk(source.root) if node.type in {'var_spec','const_spec'}]
    assert rows==[['a','b'],['c','d']]


@pytest.mark.parametrize('language,replace', [
    ('go', [('        actual :=', '        capture := func() int { return z }\n        _ = capture\n        actual :=')]),
    ('python', [('        actual =', '        def capture():\n            return z\n        actual =')]),
    ('typescript', [('        const actual =', '        const capture = () => z;\n        const actual =')]),
])
def test_nested_closure_capture_is_another_formal_use_not_a_transport_port(language, replace):
    corpus, candidate = fixture(language, replace)
    result = analyze(corpus, candidate)
    assert result['counts']['resolved_calls'] == 2
    assert result['counts']['expected_argument_ports'] == 0
    assert all(row['assertions'][0]['expected_port_reason'] == 'expected_formal_has_other_uses'
               for row in result['calls'])


def test_unproved_python_assertion_method_keeps_binding_without_edit_port():
    corpus, candidate = fixture('python', [('def test_local():', 'def test_local(checker):'),
        ('assert actual == z', 'checker.assertEqual(actual, z)')])
    result = analyze(corpus, candidate)
    assert result['counts']['resolved_calls'] == 2
    assert result['counts']['expected_argument_ports'] == 0
    assert all(row['assertions'][0]['expected_port_reason'] == 'assertion_adapter_import_unproved'
               for row in result['calls'])


def test_unimported_typescript_expect_does_not_establish_framework_origin():
    corpus, candidate = fixture('typescript', [("import { test, expect } from 'vitest';",
                                               "import { test } from 'vitest';")])
    result = analyze(corpus, candidate)
    assert result['counts']['resolved_calls'] == 2
    assert result['counts']['expected_argument_ports'] == 0


def test_method_of_local_class_is_not_a_function_binding_in_outer_test():
    corpus, candidate = fixture('python', [
        ('    def check(x, z):\n        actual = x * 2\n        assert actual == z',
         '    class C:\n        def check(x, z):\n            actual = x * 2\n            assert actual == z')])
    result = analyze(corpus, candidate)
    assert result['counts']['resolved_calls'] == 0
    assert all(row['reason'] == 'helper_declaration_in_class_scope' for row in result['calls'])


def test_source_only_snapshot_omits_runtime_probes_and_keeps_the_input_edit():
    corpus,candidate = fixture('go')
    candidate.update(program_edits=[],instrumentation=dict(status='instrumented'),
                     edits=[dict(role='relation_runtime_probe',after='bad runtime-only text')])
    result = analyze(corpus,candidate)
    assert result['counts']['resolved_calls']==2


def test_invalid_source_is_unknown_instead_of_original_graph_reuse():
    corpus,candidate = fixture('python')
    owner = corpus['tests'][candidate['base_test_id']]['span']
    begin = corpus['sources'][owner['path']]['code'].encode().index(b'check(2,4)')
    candidate['edits']=[dict(span=dict(path=owner['path'],start_byte=begin,end_byte=begin+10),
        before='check(2,4)',after='check(',role='input')]
    result=analyze(corpus,candidate)
    assert result['status']=='unknown' and result['calls']==[]
    assert result['unknowns'][0]['reason']=='modified_source_parse_error'
