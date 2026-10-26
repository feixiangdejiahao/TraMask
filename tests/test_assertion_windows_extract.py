"""Only invented source graphs; no subject execution or provider calls."""
import pytest

from prototypes.assertion_window_generation.extract import extract
from prototypes.test_edit_analogy_v02.generate import _roles
from prototypes.statement_aligned_test_analogy_v03.alignment import align_analogy
from generic_composition.corpus import build_corpus, source_text
from generic_composition.terms import render, subterms


def corpus(tmp_path, code, language='python'):
    name = {'python': 'test_windows.py', 'go': 'windows_test.go', 'typescript': 'windows.test.ts'}[language]
    (tmp_path / name).write_text(code)
    return build_corpus(tmp_path, language)


def only(data):
    result = extract(data)
    assert not result['unsupported'] and len(result['instances']) == 1
    return result['instances'][0]


def test_native_assert_window_retains_gap_and_excludes_unrelated_outer_context(tmp_path):
    data = corpus(tmp_path, '''def test_native():
    before()
    x = 1
    marker = touch()
    assert f(x) == 2
    cleanup(marker)
''')
    row = only(data)
    assert row['text'] == 'x = 1\n    marker = touch()\n    assert f(x) == 2'
    assert row['required_statement_indices'] == [0, 2]
    assert row['protected_gap_indices'] == [1]
    assert render(row['tree'].term) == source_text(data, row['span'])
    assert row['ports'][0]['roles'] == ['observed']
    assert row['ports'][1]['roles'] == ['expected']


def test_helper_local_inputs_and_expected_definitions_compose_across_parents(tmp_path):
    data = corpus(tmp_path, '''def verify(value, want):
    assert f(value) == want
def test_A():
    x = 1
    want = 2
    verify(x, want)
def test_B():
    x = [1]
    want = [2]
    verify(x, want)
def test_C():
    before()
    y = 3
    target = 6
    verify(y, target)
    after()
''')
    result = extract(data)
    assert not result['unsupported'] and len(result['instances']) == 3
    A, B, C = sorted(result['instances'], key=lambda r: r['test']['name'])
    assert C['text'] == 'y = 3\n    target = 6\n    verify(y, target)'
    assert all(r['required_statement_indices'] == [0, 1, 2] for r in (A, B, C))
    generated = align_analogy(*(r['tree'] for r in (A, B, C)), roles=_roles(A, B, C))
    assert generated.status == 'hypothesis'
    assert render(generated.output) == 'y = [3]\n    target = [6]\n    verify(y, target)'


@pytest.mark.parametrize('language,code,first,last', [
    ('go', '''package example
import "testing"
func TestWindow(t *testing.T) {
 before()
 want := 2
 x := 1
 got := f(x)
 if got != want { t.Fatalf("wrong: %v", got) }
 after()
}
''', 'want := 2', 'if got != want { t.Fatalf("wrong: %v", got) }'),
    ('go', '''package example
import "testing"
import "github.com/stretchr/testify/require"
func TestWindow(t *testing.T) {
 before()
 want := 2
 x := 1
 require.Equal(t, want, f(x))
 after()
}
''', 'want := 2', 'require.Equal(t, want, f(x))'),
    ('typescript', '''import {expect,test} from 'vitest';
test('window', () => {
 before();
 const want = 2;
 const x = 1;
 expect(f(x)).toEqual(want);
 after();
});
''', 'const want = 2;', 'expect(f(x)).toEqual(want);'),
])
def test_standard_assertion_expected_definitions_and_whole_go_guard(tmp_path,language,code,first,last):
    data = corpus(tmp_path, code, language)
    row = only(data)
    assert row['text'].startswith(first) and row['text'].endswith(last)
    assert 'before()' not in row['text'] and 'after()' not in row['text']
    assert row['protected_gap_indices'] == []
    assert source_text(data, row['statement_spans'][-1]) == last
    assert render(row['tree'].term) == row['text']


def test_control_structure_is_one_atomic_statement_not_flattened(tmp_path):
    data = corpus(tmp_path, '''def test_branch():
    enabled = ready()
    if enabled:
        x = 1
        assert f(x) == 2
    outside()
''')
    row = only(data)
    assert len(row['statement_spans']) == 2
    assert source_text(data, row['statement_spans'][-1]).startswith('if enabled:')
    assert any(node.kind == 'if_statement' for _, node in subterms(row['tree'].term))
    assert 'outside()' not in row['text']


def test_direct_mutation_recorded_but_alias_effect_is_an_explicit_graph_limit(tmp_path):
    data = corpus(tmp_path, '''def test_direct():
    values = []
    values.append(1)
    assert values == [1]
def test_alias():
    values = []
    other = values
    other.append(1)
    assert values == [1]
''')
    rows = {r['test']['name']: r for r in extract(data)['instances']}
    assert rows['test_direct']['required_statement_indices'] == [0, 1, 2]
    alias = rows['test_alias']
    assert alias['protected_gap_indices'] == [1, 2]
    assert 'other.append(1)' in alias['text']  # Included by the interval, not a claimed alias edge.
    assert 'dependency_completeness' in alias['unproved'] and 'alias_and_global_effects' in alias['unproved']


def test_same_value_expected_and_input_roles_do_not_overwrite_bindings(tmp_path):
    data = corpus(tmp_path, '''def test_same():
    input_value = 1
    wanted = 1
    assert f(input_value) == wanted
''')
    row = only(data)
    terms = dict(subterms(row['tree'].term))
    literal_roles = [(render(terms[p]), roles) for p, roles in row['literal_roles'].items() if terms[p].kind == 'integer']
    assert ('1', (('observed_definition',),)) in literal_roles
    assert ('1', (('expected_definition',),)) in literal_roles
    assert all(not terms[path].kind.endswith('identifier') for path in row['literal_roles'])
    assert any(label[0] == 'single_scope_local' for label in row['bindings'].values())


def test_unicode_comments_and_same_line_separators_remain_exact(tmp_path):
    data = corpus(tmp_path, '''# 多字节前缀
def test_unicode():
    value = "输入"; note = touch()  # 保留
    assert f(value) == "输出"
''')
    row = only(data)
    assert '; note = touch()  # 保留\n' in row['text']
    assert row['protected_gap_indices'] == [1]
    for path, node in subterms(row['tree'].term):
        s = row['tree'].spans[path]
        text = data['sources'][row['span']['path']]['code'].encode()[s.start_byte:s.end_byte].decode()
        assert render(node) == text


def test_parameter_rows_and_incomplete_sources_stay_explicitly_unsupported(tmp_path):
    data = corpus(tmp_path, '''import pytest
@pytest.mark.parametrize('value', [1,2])
def test_rows(value):
    assert f(value) == 2
''')
    assert extract(data)['skipped'] == {'parent_parameter_rows_require_instantiation': 1}
    for source in data['sources'].values():
        source['complete_file'] = False
    assert extract(data)['skipped'] == {'incomplete_or_unparseable_source': 1}


def test_helper_lexical_shadow_does_not_become_a_trusted_window(tmp_path):
    data = corpus(tmp_path, '''def verify(value, want):
    assert f(value) == want
def test_shadow():
    verify = lambda value, want: None
    verify(1, 2)
''')
    result = extract(data)
    assert not result['instances']
    assert result['skipped'] == {'helper_callee_binding_not_proved': 1}


def test_window_budget_and_results_are_deterministic(tmp_path):
    data = corpus(tmp_path, '''def test_many():
    assert f(1) == 2
    assert f(3) == 6
''')
    first = extract(data, max_instances=1)
    assert first == extract(data, max_instances=1)
    assert len(first['instances']) == 1 and first['skipped']['instance_budget'] == 1
    assert extract(data, max_nodes=2)['skipped']['instance_node_budget'] == 2


@pytest.mark.parametrize('middle,expected_literals', [
    ('    def helper():\n        expected = 99\n        return expected\n', {'2'}),
    ('    if condition:\n        expected = 99\n', {'2', '99'}),
])
def test_expected_definition_roles_respect_binding_and_conditional_may_defs(tmp_path,middle,expected_literals):
    data = corpus(tmp_path, 'def test_expected():\n    expected = 2\n' + middle +
                  '    actual = subject(1)\n    assert actual == expected\n')
    row = only(data)
    terms = dict(subterms(row['tree'].term))
    marked = {render(terms[path]) for path, roles in row['literal_roles'].items()
              if terms[path].kind == 'integer' and ('expected_definition',) in roles}
    assert marked == expected_literals


def test_expected_chain_and_shared_input_keep_source_roles(tmp_path):
    data = corpus(tmp_path, '''def test_expected():
    value = 2
    wanted = expected_builder(value)
    actual = subject(value)
    assert actual == wanted
''')
    row = only(data)
    terms = dict(subterms(row['tree'].term))
    roles = next(roles for path, roles in row['literal_roles'].items() if terms[path].kind == 'integer')
    assert ('expected_definition',) in roles and ('observed_definition',) in roles
