from pathlib import Path

from generic_composition.corpus import build_corpus, source_text


def write(tmp_path, filename, code):
    path = tmp_path / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(code)
    return path


def test_python_capsule_keeps_state_prefix_atoms_and_exact_unicode_bytes(tmp_path):
    code = '''from imaginary import make
def test_state():
    label = "中文"
    box = make(label)
    box.add(7)
    value = box.read()
    assert value == {"sum": 7, "history": [1, 6]}
'''
    write(tmp_path, 'test_box.py', code)
    corpus = build_corpus(tmp_path, 'python')
    capsule = corpus['capsules'][0]
    assert capsule['observed']['text'] == 'value'
    assert source_text(corpus, capsule['observed']['span']) == 'value'
    assert 'box.add(7)' in source_text(corpus, capsule['prefix_span'])
    assert [a['projection'] for a in capsule['expected_atoms']] == [['sum'], ['history', 0], ['history', 1]]
    assert capsule['bindings']['alias_precision'] == 'unknown'
    assert {'make', 'box.add', 'box.read'} <= {c['callee'] for c in capsule['calls']}
    assert corpus['sources']['test_box.py']['code'] == code
    donor = next(d for d in corpus['donors'] if d.get('text') == 'label')
    assert donor['free_identifiers'] == ['label']
    assert donor['call_context']['callee'] == 'make'
    assert donor['call_context']['argument_slot'] == 0


def test_pytest_rows_keep_correlated_inputs_and_expected_with_cell_spans(tmp_path):
    write(tmp_path, 'test_rows.py', '''import pytest
@pytest.mark.parametrize("x, expected", [("a", 1), ("bb", 2)])
def test_width(x, expected):
    assert width(x) == expected
''')
    corpus = build_corpus(tmp_path, 'python')
    rows = [d for d in corpus['donors'] if d['kind'] == 'parameter_row']
    assert [r['parameter_bindings'] for r in rows] == [{'x': 'a', 'expected': 1}, {'x': 'bb', 'expected': 2}]
    assert source_text(corpus, rows[1]['binding_sources']['expected']['span']) == '2'
    assert source_text(corpus, rows[1]['row_span']) == '("bb", 2)'
    assert corpus['capsules'][0]['parameter_rows'][0]['coupled']
    assert source_text(corpus, corpus['capsules'][0]['test_span']).startswith('@pytest.mark.parametrize')


def test_go_helper_maps_expected_formal_to_actual_and_does_not_parse_guest(tmp_path):
    write(tmp_path, 'calc_test.go', '''package calc
import "github.com/stretchr/testify/require"
func check(t *testing.T, input string, want int) {
    got := execute(input)
    require.Equal(t, want, got)
}
func TestCase(t *testing.T) {
    check(t, `not_a_language { "field": 9 }`, 9)
}
''')
    corpus = build_corpus(tmp_path, 'go')
    capsule = corpus['capsules'][0]
    mapping = capsule['helper_assertions'][0]
    assert mapping['status'] == 'direct_parameter'
    assert mapping['caller_expected']['text'] == '9'
    assert mapping['expected_parameter_origins'][0]['parameter'] == 'want'
    guest = next(d for d in corpus['donors'] if d.get('kind') == 'raw_string_literal')
    assert guest['embedded_language'] == 'opaque'
    assert guest['literal_value'] == 'not_a_language { "field": 9 }'


def test_helper_converted_expectation_is_explicitly_unsupported(tmp_path):
    write(tmp_path, 'calc_test.go', '''package calc
import "github.com/stretchr/testify/require"
func check(t *testing.T, input string, want int) {
    converted := convert(want)
    require.Equal(t, converted, execute(input))
}
func TestCase(t *testing.T) { check(t, "abc", 7) }
''')
    mapping = build_corpus(tmp_path, 'go')['capsules'][0]['helper_assertions'][0]
    assert mapping['caller_expected'] is None
    assert mapping['status'] == 'unsupported_expected_transform_or_constant'
    assert mapping['expected_parameter_origins'][0]['actual']['text'] == '7'


def test_typescript_structural_expected_atoms_and_anonymous_tokens(tmp_path):
    write(tmp_path, 'opaque.test.ts', '''import { expect, test } from 'vitest';
test('shape', () => {
  const result = opaque({ title: 'hi' });
  expect(result).toStrictEqual({ answer: 4, nested: [{ ok: true }] });
});
''')
    corpus = build_corpus(tmp_path, 'typescript')
    capsule = corpus['capsules'][0]
    assert capsule['observed']['text'] == 'result'
    assert [a['projection'] for a in capsule['expected_atoms']] == [['answer'], ['nested', 0, 'ok']]
    ast = capsule['expected']['ast']
    assert ast['children'][0]['text'] == '{'
    donor = next(d for d in corpus['donors'] if d.get('text') == "{ title: 'hi' }")
    assert donor['call_context']['callee'] == 'opaque'
    assert donor['free_identifiers'] == []


def test_retrieval_priority_and_directory_round_robin_are_deterministic(tmp_path):
    for filename in ['aaa/test_a.py', 'aaa/test_b.py', 'zzz/test_z.py']:
        write(tmp_path, filename, 'def test_value():\n    assert run(3) == 3\n')
    retrieval = {'selected_tests': [{'rank': 1, 'path': 'zzz/test_z.py', 'line': 1, 'name': 'test_value'}]}
    a = build_corpus(tmp_path, 'python', retrieval, max_files=2)
    b = build_corpus(tmp_path, 'python', retrieval, max_files=2)
    assert a == b
    assert a['capsules'][0]['retrieval_rank'] == 1
    assert set(a['sources']) == {'zzz/test_z.py', 'aaa/test_a.py'}
    assert a['coverage']['file_budget_exhausted']


def test_repeated_assertion_text_keeps_each_original_span(tmp_path):
    write(tmp_path, 'test_again.py', '''def test_again():
    assert run(1) == 1
    bump()
    assert run(1) == 1
''')
    corpus = build_corpus(tmp_path, 'python')
    first, second = corpus['capsules']
    assert first['id'] != second['id']
    assert second['assertion_span']['line'] == 4
    assert 'bump()' in source_text(corpus, second['prefix_span'])


def test_distinct_historical_excerpts_retain_rank_and_incomplete_source_flag(tmp_path):
    retrieval = {'selected_tests': [
        {'rank': 1, 'path': 'trajectory/snippet.go', 'line': 25, 'name': 'TestFirst',
         'code': 'func TestFirst(t *testing.T) { require.Equal(t, 1, run()) }'},
        {'rank': 2, 'path': 'trajectory/snippet.go', 'line': 40, 'name': 'TestSecond',
         'code': 'func TestSecond(t *testing.T) { require.Equal(t, 2, run()) }'},
    ]}
    corpus = build_corpus(tmp_path, 'go', retrieval)
    assert [c['retrieval_rank'] for c in corpus['capsules']] == [1, 2]
    assert len(corpus['sources']) == 2
    assert all(not s['complete_file'] for s in corpus['sources'].values())
    assert all('historical_excerpt_missing_full_file_support' in c['unknowns'] for c in corpus['capsules'])


def test_typescript_keeps_lexical_insertion_scope(tmp_path):
    write(tmp_path, 'scope.test.ts', '''describe('outer', () => {
  const input = 5;
  test('inner', () => { expect(run(input)).toBe(5); });
});
''')
    corpus = build_corpus(tmp_path, 'typescript')
    test = next(iter(corpus['tests'].values()))
    outer = source_text(corpus, test['enclosing_scope_span'])
    assert 'const input = 5' in outer
    assert source_text(corpus, test['span']).startswith("test('inner'")
    assert corpus['sources']['scope.test.ts']['code'].encode()[test['insertion_after_byte'] - 1] == ord(';')


def test_alias_canonicalization_and_assigned_literal_reach_input_slot(tmp_path):
    write(tmp_path, 'test_one.py', '''from widgets import submit as send
def test_one():
    payload = "abc"
    actual = send(payload)
    assert actual == {"size": 3}
''')
    write(tmp_path, 'test_two.py', '''from widgets import submit
def test_two():
    assert submit("xy") == {"size": 2}
''')
    corpus = build_corpus(tmp_path, 'python')
    literals = [d for d in corpus['donors'] if d.get('literal_value') in ('abc', 'xy')]
    assert len(literals) == 2
    identities = {d['input_slots'][0]['callee_identity']['canonical'] for d in literals}
    assert identities == {'widgets::submit'}
    assert all(d['input_slots'][0]['argument_slot'] == 0 for d in literals)
    atom = corpus['capsules'][0]['expected_atoms'][0]
    assert atom['observed_provenance'][0]['callee_identity']['canonical'] == 'widgets::submit'
    assert atom['provenance_precision'].endswith('field_specific_producer_unknown')


def test_budget_round_robin_and_registration_scaffolding_are_not_donors(tmp_path):
    write(tmp_path, 'many.test.ts', '''test('large registration label', () => {
 const first = outer(inner(1));
 expect(first).toBe(1);
 expect(first).toBe(2);
 expect(first).toBe(3);
});
test('small registration label', () => { expect(other(9)).toBe(9); });
''')
    corpus = build_corpus(tmp_path, 'typescript', max_donors=4, max_capsules=2)
    assert len({d['test_id'] for d in corpus['donors']}) == 2
    assert len({a['test_id'] for a in corpus['capsules']}) == 2
    assert all('registration label' not in d.get('text', '') for d in corpus['donors'])
    assert all(d['kind'] != 'arrow_function' for d in corpus['donors'])


def test_whole_call_rhs_and_parent_context_are_available_without_api_rules(tmp_path):
    write(tmp_path, 'test_context.py', '''def test_context():
    value = enclose(adapt(3))
    assert value == 3
''')
    corpus = build_corpus(tmp_path, 'python')
    donors = {d.get('text'): d for d in corpus['donors']}
    assert 'enclose(adapt(3))' in donors
    assert donors['adapt(3)']['context_parent']['text'] == 'enclose(adapt(3))'
    assert donors['adapt(3)']['call_context']['argument_slot'] == 0
    assert donors['adapt(3)']['context_relation_status'].endswith('no_equivalence_claim')


def test_identical_input_and_expected_literals_keep_distinct_oracle_spans(tmp_path):
    examples = [
        ('python', 'test_one.py', 'def test_one():\n    assert make(1) == 1\n'),
        ('go', 'one_test.go', 'package one\nfunc TestOne(t *testing.T) { require.Equal(t, 1, make(1)) }'),
        ('typescript', 'one.test.ts', "test('one', () => { expect(make(1)).toBe(1); });"),
    ]
    for language, path, code in examples:
        directory = tmp_path / language
        write(directory, path, code)
        corpus = build_corpus(directory, language)
        capsule = corpus['capsules'][0]
        ones = [d for d in corpus['donors'] if d.get('text') == '1']
        expected = next(d for d in ones if d['span'] == capsule['expected']['span'])
        actual = next(d for d in ones if d['span'] != capsule['expected']['span'])
        assert expected['role'] == 'expected'
        assert actual['role'] == 'test_expression'
        assert actual['call_context']['callee'] == 'make'


def test_shared_object_alias_is_observed_and_expected_without_predicate_exceptions(tmp_path):
    write(tmp_path, 'test_alias.py', '''def test_alias():
    value = build({"kind": "leaf"})
    alias = value
    assert alias.child is value
''')
    corpus = build_corpus(tmp_path, 'python')
    donor = next(d for d in corpus['donors'] if d.get('text') == '"leaf"')
    assert donor['oracle_dependency']
    assert donor['observation_dependency']
    assert donor['dependency_role'] == 'observed_and_expected'


def test_expected_only_helper_value_is_not_an_actual_dependency(tmp_path):
    write(tmp_path, 'test_helper.py', '''def check(actual, wanted):
    assert actual == wanted
def test_separate():
    payload = "item:1"
    wanted = "want:1"
    check(parse(payload), wanted)
''')
    corpus = build_corpus(tmp_path, 'python')
    wanted = next(d for d in corpus['donors'] if d.get('text') == '"want:1"')
    payload = next(d for d in corpus['donors'] if d.get('text') == '"item:1"')
    assert wanted['oracle_dependency'] and not wanted['observation_dependency']
    assert payload['observation_dependency'] and not payload['oracle_dependency']
    mapping = corpus['capsules'][0]['helper_assertions'][0]
    assert [b['parameter'] for b in mapping['observed_parameter_origins']] == ['actual']


def test_readonly_input_relation_reaches_actual_via_call_and_expected_via_alias(tmp_path):
    write(tmp_path, 'test_input.py', '''def verify(actual, wanted):
    assert actual == wanted
def test_input():
    data = ["original"]
    before = data
    returned = inspect(data)
    verify(returned, before)
''')
    corpus = build_corpus(tmp_path, 'python')
    donor = next(d for d in corpus['donors'] if d.get('text') == '"original"')
    assert donor['dependency_role'] == 'observed_and_expected'
    assert corpus['capsules'][0]['observation_dependency_precision'].startswith('actual_only_value_edges')


def test_actual_trace_excludes_control_edges_and_synthetic_join_spans(tmp_path):
    write(tmp_path, 'test_branch.py', '''def test_branch():
    wanted = "wanted"
    if wanted:
        result = run("input")
    else:
        result = run("fallback")
    assert result == wanted
''')
    corpus = build_corpus(tmp_path, 'python')
    wanted = next(d for d in corpus['donors'] if d.get('text') == '"wanted"')
    assert wanted['oracle_dependency'] and not wanted['observation_dependency']
    inputs = [d for d in corpus['donors'] if d.get('text') in {'"input"', '"fallback"'}]
    assert all(d['observation_dependency'] for d in inputs)


def test_actual_trace_does_not_follow_uncertain_effect_of_prior_assertion_helper(tmp_path):
    write(tmp_path, 'test_effect.py', '''def check(actual, wanted):
    assert actual == wanted
def test_effect():
    data = ["input"]
    wanted = ["expected"]
    check(data, wanted)
    assert observe(data) == []
''')
    corpus = build_corpus(tmp_path, 'python')
    wanted = next(d for d in corpus['donors'] if d.get('text') == '"expected"')
    assert wanted['oracle_dependency'] and not wanted['observation_dependency']


def test_shared_value_roles_are_language_independent(tmp_path):
    examples = [
        ('go', 'roles_test.go', '''package roles
func TestRoles(t *testing.T) {
    source := makeValue("seed")
    alias := source
    require.Equal(t, source, alias)
}'''),
        ('typescript', 'roles.test.ts', '''test('roles', () => {
  const source = makeValue('seed');
  const alias = source;
  expect(alias).toStrictEqual(source);
});'''),
    ]
    for language, path, code in examples:
        directory = tmp_path / language
        write(directory, path, code)
        corpus = build_corpus(directory, language)
        donor = next(d for d in corpus['donors'] if d.get('literal_value') == 'seed')
        assert donor['observation_dependency'] and donor['oracle_dependency']
