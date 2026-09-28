import pytest

from anchor_retrieval.syntax import Source
from relational_gap.frontend import extract_frontend, to_emitter_corpus
from relational_gap.source_expected_values import resolve_expected_constant


def check(code, language='python', edits=()):
    path = {'python': 'test_values.py', 'go': 'values_test.go', 'typescript': 'values.test.ts'}[language]
    facts = extract_frontend([Source(path, code, language)])
    corpus = to_emitter_corpus(facts)
    q = next(q for q in facts['observations'] if q.get('expected'))
    return resolve_expected_constant(corpus, q['test_id'], q['expected']['span'], edits=edits), corpus, q


@pytest.mark.parametrize('language,code,value', [
    ('python', 'def test_value():\n    want = "résultat"\n    alias = want\n    assert subject() == alias\n', 'résultat'),
    ('typescript', 'test("value", () => { const want = "ok"; expect(subject()).toBe(want); });', 'ok'),
    ('go', 'package p\nimport "testing"\nfunc TestValue(t *testing.T) { want := "\\x1b[0m"; if subject() != want { t.Fatal("bad") } }', '\x1b[0m'),
    ('go', 'package p\nimport "testing"\nfunc TestValue(t *testing.T) { var want = 7; if subject() != want { t.Fatal("bad") } }', 7),
])
def test_prior_local_primitive_alias_is_recovered_without_subject_execution(language, code, value):
    result, _, _ = check(code, language)
    assert result['known'] and result['value'] == value
    assert result['source_spans']


@pytest.mark.parametrize('setup', [
    'want = []',
    'want = subject()',
    'if condition:\n        want = 3',
    'want = 1\n    want += 2',
    'want = 1\n    for want in [3]:\n        pass',
    'want = 1\n    def change():\n        nonlocal want\n        want = 3\n    change()',
])
def test_ambiguous_effectful_or_mutable_expected_values_stay_unknown(setup):
    result, _, _ = check('def test_value():\n    ' + setup + '\n    assert subject() == want\n')
    assert result['known'] is False


def test_edited_expected_definition_is_not_exposed_as_current_constant():
    code = 'def test_value():\n    want = "ok"\n    assert subject() == want\n'
    _, corpus, q = check(code)
    start = code.index('"ok"')
    edit = {'span': {'path': 'test_values.py', 'start_byte': start, 'end_byte': start + 4}, 'before': '"ok"', 'after': '"bad"'}
    assert resolve_expected_constant(corpus, q['test_id'], q['expected']['span'], edits=[edit])['reason'] == 'expected_definition_is_edited'


def test_go_address_escape_invalidates_local_primitive_recovery():
    code = 'package p\nimport "testing"\nfunc TestValue(t *testing.T) { want := 7; modify(&want); if subject() != want { t.Fatal("bad") } }'
    assert check(code, 'go')[0]['known'] is False


def test_local_shadow_in_block_is_not_mistaken_for_unique_outer_definition():
    code = 'test("value", () => { const want = "ok"; if (cond) { const want = "other"; expect(subject()).toBe(want); } });'
    assert check(code, 'typescript')[0]['known'] is False


@pytest.mark.parametrize('write', ['want = 2;', 'want += 2;', '({want} = other);'])
def test_typescript_reassignment_does_not_recover_stale_expected_value(write):
    code = 'test("value", () => { let want = 1; ' + write + ' expect(subject()).toBe(want); });'
    assert check(code, 'typescript')[0]['known'] is False


def test_callback_parameter_does_not_resolve_to_outer_literal():
    code = 'test("value", () => { const want = 1; [2].forEach((want) => {expect(subject()).toBe(want);}); });'
    assert check(code, 'typescript')[0]['known'] is False


@pytest.mark.parametrize('control', [
    'with resource() as want:\n        assert subject() == want',
    'match value:\n        case want:\n            assert subject() == want',
])
def test_python_control_binding_does_not_resolve_to_outer_literal(control):
    assert check('def test_value():\n    want = 1\n    ' + control + '\n')[0]['known'] is False
