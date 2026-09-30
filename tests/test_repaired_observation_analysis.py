"""Source-path repairs tested independently of pilots and target labels."""
import copy

import pytest

from experimental.patch_observation_priority_cached import Analyzer as CachedAnalyzer
from experimental.repaired_observation_analysis import Analyzer
from tests.test_patch_observation_priority import candidate, fixture


def facts(corpus, front, patch, row, **kwargs):
    return Analyzer(corpus, front, patch, **kwargs).evidence(row)


def test_inline_actual_input_has_same_patch_dependency_as_separate_input():
    c, f, p = fixture(body='assert compute(11) == 22')
    row = candidate(c)
    assert not CachedAnalyzer(c, f, p).evidence(row)['strong_priority']
    fixed = facts(c, f, p, row)
    assert fixed['strong_priority']
    assert fixed['witnesses'][0]['patch_span']['path'] == 'library.py'
    assert fixed['source_repairs']['observations'][0]['basis'] == 'actual_edit_with_unchanged_checker_bytes'


@pytest.mark.parametrize('before,after', [('22', '33'), ('==', '!='),
                                        ('assert compute(11) == 22', 'pass')])
def test_oracle_or_statement_edit_does_not_inherit_observation(before, after):
    c, f, p = fixture(body='assert compute(11) == 22')
    assert not facts(c, f, p, candidate(c, before, after))['strong_priority']


def test_inline_callee_change_rebinds_instead_of_inheriting_patched_function():
    old = 'def compute(value):\n    return value * 2\ndef neutral(value):\n    return value\n'
    c, f, p = fixture(old, old.replace('* 2', '* 3'),
                      body='from library import neutral\nassert compute(11) == 22')
    row = candidate(c, 'compute(11)', 'neutral(19)')
    fixed = facts(c, f, p, row)
    assert fixed['source_repairs']['observations'][0]['status'] == 'corresponding'
    assert not fixed['strong_priority'] and not fixed['may_priority']


@pytest.mark.parametrize('signature,call', [
    ('value', 'compute(value=value)'),
    ('*, value', 'compute(value=value)'),
    ('value=5', 'compute(value)'),
    ('value, /', 'compute(value)'),
])
def test_explicit_legal_argument_binding_restores_source_return_path(signature, call):
    old = f'def compute({signature}):\n    return value * 2\n'
    c, f, p = fixture(old, old.replace('* 2', '* 3'),
                      body=f'value = 11\nresult = {call}\nassert result == 22')
    assert facts(c, f, p, candidate(c))['strong_priority']


@pytest.mark.parametrize('signature,call,reason', [
    ('*, value', 'compute(value)', 'excess_positional_arguments'),
    ('value, /', 'compute(value=value)', 'positional_only_supplied_as_keyword'),
    ('value', 'compute(value, value=value)', 'duplicate_argument_binding'),
    ('value', 'compute(value=value, value=value)', 'duplicate_keyword_argument'),
])
def test_illegal_argument_binding_cannot_supply_a_strong_path(signature, call, reason):
    old = f'def compute({signature}):\n    return value * 2\n'
    c, f, p = fixture(old, old.replace('* 2', '* 3'),
                      body=f'value = 11\nresult = {call}\nassert result == 22')
    result = facts(c, f, p, candidate(c))
    assert not result['strong_priority']
    assert reason in result['unknowns']


def test_omitted_defaults_are_not_evaluated_or_assigned_a_graph_value():
    old = 'def compute(value, factor=2):\n    return value * factor\n'
    c, f, p = fixture(old, old.replace('value * factor', 'value * factor + 1'))
    result = facts(c, f, p, candidate(c))
    assert not result['strong_priority']
    assert 'omitted_formal_not_supported' in result['unknowns']


def test_disabling_both_repairs_retains_cached_evidence_exactly():
    c, f, p = fixture(body='assert compute(11) == 22')
    row = candidate(c)
    old = CachedAnalyzer(c, f, p, disable_receiver_fix=True).evidence(row)
    new = facts(c, f, p, row, repair_correspondence=False, repair_arguments=False, disable_receiver_fix=True)
    del new['source_repairs']
    assert new == old


def test_reused_analyzer_keeps_changed_owner_bindings_and_source_identity_separate():
    c, f, p = fixture(body='assert compute(11) == 22')
    rows = [candidate(c, after='19'), candidate(c, after='123456'), candidate(c, '22', '33')]
    frozen = copy.deepcopy((c, f, rows)); analyzer = Analyzer(c, f, p)
    for row in rows + rows[::-1]:
        assert analyzer.evidence(row) == facts(c, f, p, row)
    assert (c, f, rows) == frozen


@pytest.mark.parametrize('language,old,new,body', [
    ('go', 'package sample\nfunc compute(value int) int {return value * 2}\n',
     'package sample\nfunc compute(value int) int {return value * 3}\n',
     'package sample\nimport "testing"\nfunc TestCase(t *testing.T){if compute(11)!=22{t.Error("wrong")}}\n'),
    ('typescript', 'export function compute(value: number): number {return value * 2;}\n',
     'export function compute(value: number): number {return value * 3;}\n',
     'import {compute} from "./library";\ntest("case",()=>{expect(compute(11)).toBe(22);});\n'),
])
def test_inline_observation_repair_recovers_language_neutral_patch_return_queries(language, old, new, body):
    c, f, p = fixture(old, new, body, language); row = candidate(c)
    assert not CachedAnalyzer(c, f, p).evidence(row)['strong_priority']
    fixed = facts(c, f, p, row)
    assert fixed['strong_priority'], fixed['unknowns']


def test_keyword_followed_by_positional_source_syntax_is_not_a_proved_binding():
    old = 'def compute(value, factor):\n    return value * factor\n'
    c, f, p = fixture(old, old.replace('value * factor', 'value * factor + 1'),
                      body='value = 11\nresult = compute(factor=2, value)\nassert result == 22')
    result = facts(c, f, p, candidate(c))
    assert not result['strong_priority']
    assert 'positional_argument_after_keyword' in result['unknowns']


def test_actual_expected_role_flip_cannot_reuse_the_old_observation_label():
    c, f, p = fixture(body='value = 11\nassert compute(11) == compute(value)')
    row = candidate(c, before='11', after='19')
    row['edits'].extend(candidate(c, 'compute(11)', '0')['edits'])
    result = facts(c, f, p, row)
    assert not result['strong_priority']
    assert 'modified_actual_role_differs_from_source_observation' in result['unknowns']


@pytest.mark.parametrize('after', ['19', '123456'])
def test_role_identity_uses_utf8_byte_spans_when_line_metadata_differs(after):
    c, f, p = fixture(body='label = "雪"\nassert compute(11) == 22')
    result = facts(c, f, p, candidate(c, after=after))
    assert result['strong_priority']
    mapping = result['source_repairs']['observations'][0]
    actual = result['witnesses'][0]['actual_span']
    # The transporter and AST adapter expose different display metadata,
    # while denoting exactly the same modified source bytes.
    assert 'line' not in mapping['actual_span'] and 'line' in actual
    assert (mapping['actual_span']['path'], mapping['actual_span']['start_byte'],
            mapping['actual_span']['end_byte']) == (
                actual['path'], actual['start_byte'], actual['end_byte'])
    assert 'modified_actual_role_differs_from_source_observation' not in result['unknowns']
    assert 'modified_expected_role_differs_from_source_observation' not in result['unknowns']


def test_repeated_assertions_keep_distinct_roles_at_each_source_stage():
    c, f, p = fixture(body='value = 11\nassert compute(value) == 22\nassert compute(value) == 22')
    result = facts(c, f, p, candidate(c))
    assert result['strong_priority']
    assert len(result['witnesses']) == 2
    assert {row['observation_id'] for row in result['witnesses']} == {
        row['id'] for row in f['observations']}
    assert len({row['actual_span']['start_byte'] for row in result['witnesses']}) == 2


@pytest.mark.parametrize('mismatch', ['other_stage', 'other_path'])
def test_expected_role_must_match_its_own_source_location(mismatch):
    c, f, p = fixture(body='value = 11\nassert compute(value) == 22\nassert compute(value) == 22')
    front = copy.deepcopy(f)
    first, second = front['observations']
    wrong = copy.deepcopy(first['expected']['span'])
    if mismatch == 'other_path':
        wrong['path'] = 'other_test.py'
    second['expected']['span'] = wrong
    result = facts(c, front, p, candidate(c))
    assert [row['observation_id'] for row in result['witnesses']] == [first['id']]
    assert 'modified_expected_role_differs_from_source_observation' in result['unknowns']


@pytest.mark.parametrize('body,before,after', [
    ('assert compute(11) == 22 and 1 == 1',
     'compute(11) == 22', 'compute(19) != 22'),
    ('assert 0 < compute(11) < 22',
     'compute(11) < 22', 'compute(19) > 22'),
])
def test_combined_input_and_compound_checker_edit_cannot_inherit_a_strong_observation(body, before, after):
    c, f, p = fixture(body=body)
    result = facts(c, f, p, candidate(c, before, after))
    assert not result['strong_priority'] and not result['may_priority']
    assert result['source_repairs']['observations'][0]['reason'] == 'actual_and_checker_roles_not_separated'


def test_invalid_positional_order_is_rejected_even_when_import_records_restore_the_callee():
    old = 'def compute(value, factor):\n    return value * factor * 2\n'
    c, f, p = fixture(old, old.replace('* 2', '* 3'),
                      body='value = 11\nresult = compute(value, 2)\nassert result == 44')
    row = candidate(c, 'compute(value, 2)', 'compute(factor=2, value)')
    row['edits'].extend(candidate(c)['edits'])
    row['imports'] = [dict(name='compute', module='library', imported_name='compute')]
    result = facts(c, f, p, row)
    assert not result['strong_priority'] and not result['may_priority']
    assert 'positional_argument_after_keyword' in result['unknowns']
