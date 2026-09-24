"""Finite input evaluation uses only invented parameter tables and source ASTs."""
import copy

import pytest

from experimental import finite_inputs
from experimental.finite_inputs import augment_corpus
from generic_composition.corpus import build_corpus
from generic_composition.engine import Budget, expanded_donors, generate


def corpus_for(tmp_path, code):
    (tmp_path / 'test_finite.py').write_text(code)
    return build_corpus(tmp_path, 'python')


def additions(corpus):
    return [donor for donor in corpus['donors'] if donor.get('finite_input')]


def test_fstring_rows_preserve_original_spans_ports_and_whole_correlated_row(tmp_path):
    corpus = corpus_for(tmp_path, '''# 多字节位置
import pytest
@pytest.mark.parametrize("value, width, expected", [(3, 2, "03"), (8, 3, "008")])
def test_toy(value, width, expected):
    raw = f"{value:0{width}d}"
    assert process(raw) == expected
''')
    before = copy.deepcopy(corpus)
    enriched = augment_corpus(corpus)
    assert corpus == before
    assert enriched is not corpus and enriched['donors'] is not corpus['donors']
    assert all(enriched[key] is corpus[key] for key in ('sources', 'capsules', 'tests'))
    values = additions(enriched)
    assert [row['literal_value'] for row in values] == ['03', '008']
    original = next(donor for donor in corpus['donors'] if donor.get('text') == 'f"{value:0{width}d}"')
    for donor in values:
        assert donor['literal_known']
        for key in ('span', 'text', 'ast', 'input_slots', 'call_context', 'free_identifiers'):
            assert donor[key] == original[key]
        row = donor['parameter_row']
        assert row['name'] is None
        assert row['bindings']['expected'] == donor['literal_value']
        assert donor['finite_input']['referenced_parameters'] == ['value', 'width']
        assert set(donor['finite_input']['binding_sources']) == {'value', 'width', 'expected'}
    assert [row['id'] for row in additions(augment_corpus(enriched))] == [row['id'] for row in values]


def test_augmented_inputs_participate_in_existing_context_learning(tmp_path):
    corpus = corpus_for(tmp_path, '''import pytest
@pytest.mark.parametrize("value, expected", [(1, 1), (2, 2), (3, 3)])
def test_toy(value, expected):
    assert process(f"item:{value}:done") == expected
''')
    enriched = augment_corpus(corpus)
    finite = {donor['id']: donor for donor in additions(enriched)}
    assert len(finite) == 3
    expanded = {donor['id']: donor for donor in expanded_donors(enriched)}
    assert finite.keys() <= expanded.keys()
    generated = generate(enriched, Budget(max_candidates=16))
    candidates = [row for row in generated['candidates'] if row['provenance']['target_donor_id'] in finite]
    assert candidates
    for candidate in candidates:
        donor = finite[candidate['provenance']['target_donor_id']]
        assert candidate['edits'][0]['span'] == donor['span']
        assert candidate['edits'][0]['before'] == donor['text']
        assert donor['parameter_row']['name'] == 'value'


@pytest.mark.parametrize('expression, expected', [
    ('"prefix:" + value + ":tail"', 'prefix:a:tail'),
    ('f"{value!r}:{number + 2:03d}"', "'a':005"),
    ('f"{{{value}}}"', '{a}'),
    ('f"{number=}"', 'number=3'),
])
def test_pure_addition_and_builtin_format_match_python_values(tmp_path, expression, expected):
    corpus = corpus_for(tmp_path, '''import pytest
@pytest.mark.parametrize("value, number, expected", [("a", 3, 1)])
def test_toy(value, number, expected):
    assert process(''' + expression + ''') == expected
''')
    donor = next(row for row in additions(augment_corpus(corpus)) if row['text'] == expression)
    assert donor['literal_value'] == expected


@pytest.mark.parametrize('expression', [
    'f"{danger(value)}"', 'f"{value.upper()}"', '"{}".format(value)',
    'f"{value.real}"', 'f"{unknown}"', 'f"{(value := 2)}"',
])
def test_calls_attributes_unknown_names_and_side_effects_are_not_evaluated(tmp_path, expression):
    corpus = corpus_for(tmp_path, '''import pytest
def danger(value): raise AssertionError("must never execute")
@pytest.mark.parametrize("value, expected", [("a", 1)])
def test_toy(value, expected):
    assert process(''' + expression + ''') == expected
''')
    assert not any(row['text'] == expression for row in additions(augment_corpus(corpus)))


@pytest.mark.parametrize('prefix', ['    value = "changed"\n', '    value += "changed"\n',
                                  '    if condition:\n        value = "changed"\n'])
def test_prior_parameter_rebinding_invalidates_static_row_value(tmp_path, prefix):
    corpus = corpus_for(tmp_path, '''import pytest
@pytest.mark.parametrize("value, expected", [("a", 1)])
def test_toy(value, expected):
''' + prefix + '''    assert process(f"{value}") == expected
''')
    result = augment_corpus(corpus)
    assert additions(result) == []
    assert result['finite_inputs']['skipped']['parameter_binding_may_have_changed']


def test_row_binding_reassignment_after_expression_requires_richer_materialization(tmp_path):
    corpus = corpus_for(tmp_path, '''import pytest
@pytest.mark.parametrize("value, expected", [("a", 1)])
def test_toy(value, expected):
    raw = f"{value}"
    value = "later"
    assert process(raw) == expected
''')
    result = augment_corpus(corpus)
    assert additions(result) == []
    assert result['finite_inputs']['skipped']['parameter_row_bindings_may_change']


def test_loop_backedge_rebinding_changes_later_dynamic_evaluations(tmp_path):
    corpus = corpus_for(tmp_path, '''import pytest
@pytest.mark.parametrize("value, expected", [("a", 1)])
def test_toy(value, expected):
    for repeat in range(2):
        assert process(f"{value}") == expected
        value = "changed"
''')
    result = augment_corpus(corpus)
    assert additions(result) == []
    assert result['finite_inputs']['skipped']['parameter_binding_may_change_on_loop_backedge']


def test_inner_function_binding_is_not_an_outer_parameter_row(tmp_path):
    corpus = corpus_for(tmp_path, '''import pytest
@pytest.mark.parametrize("value, expected", [("a", 1)])
def test_toy(value, expected):
    def helper(value):
        return process(f"{value}")
    assert helper("other") == expected
''')
    assert not any(row['text'] == 'f"{value}"' for row in additions(augment_corpus(corpus)))


def test_missing_expected_cell_rejects_whole_row_without_cross_row_repair(tmp_path):
    corpus = corpus_for(tmp_path, '''import pytest
@pytest.mark.parametrize("value, expected", [("a", 1), ("b", 2)])
def test_toy(value, expected):
    assert process(f"{value}") == expected
''')
    row = next(donor for donor in corpus['donors'] if donor['kind'] == 'parameter_row' and donor['row'] == 0)
    del row['parameter_bindings']['expected']
    values = additions(augment_corpus(corpus))
    assert len(values) == 1
    assert values[0]['parameter_row'] == {'table': 0, 'row': 1, 'name': 'value', 'bindings': {'value': 'b', 'expected': 2}}


def test_indirect_rows_and_multiple_tables_do_not_claim_actual_argument_values(tmp_path):
    corpus = corpus_for(tmp_path, '''import pytest
@pytest.mark.parametrize("value, expected", [("a", 1)], indirect=True)
def test_toy(value, expected):
    assert process(f"{value}") == expected
''')
    result = augment_corpus(corpus)
    assert additions(result) == []
    assert result['finite_inputs']['skipped']['indirect_parameter_values_unknown']
    corpus = corpus_for(tmp_path, '''import pytest
@pytest.mark.parametrize("value", ["a"])
@pytest.mark.parametrize("expected", [1])
def test_toy(value, expected):
    assert process(f"{value}") == expected
''')
    assert additions(augment_corpus(corpus)) == []


def test_bool_and_int_rows_preserve_python_format_types(tmp_path):
    corpus = corpus_for(tmp_path, '''import pytest
@pytest.mark.parametrize("value, expected", [(True, "True:1"), (1, "1:1")])
def test_toy(value, expected):
    assert process(f"{value!s}:{value:d}") == expected
''')
    values = additions(augment_corpus(corpus))
    assert [row['literal_value'] for row in values] == ['True:1', '1:1']
    assert type(values[0]['parameter_row']['bindings']['value']) is bool
    assert type(values[1]['parameter_row']['bindings']['value']) is int


@pytest.mark.parametrize('import_line, decorator', [
    ('import other as fake', 'fake.parametrize'),
    ('import other as fake', 'fake.mark.parametrize'),
    ('import pytest\npytest = other', 'pytest.mark.parametrize'),
    ('import pytest\npytest.mark = other', 'pytest.mark.parametrize'),
])
def test_parameter_table_requires_resolved_pytest_decorator(tmp_path, import_line, decorator):
    corpus = corpus_for(tmp_path, import_line + '\n@' + decorator + '''("value, expected", [("a", 1)])
def test_toy(value, expected):
    assert process(f"{value}") == expected
''')
    assert additions(augment_corpus(corpus)) == []


def test_pytest_module_import_alias_is_resolved(tmp_path):
    corpus = corpus_for(tmp_path, '''import pytest as p
@p.mark.parametrize("value, expected", [("a", 1)])
def test_toy(value, expected):
    assert process(f"{value}") == expected
''')
    assert [row['literal_value'] for row in additions(augment_corpus(corpus))] == ['a']


def test_locale_sensitive_format_is_not_assumed_constant(tmp_path):
    corpus = corpus_for(tmp_path, '''import pytest
@pytest.mark.parametrize("value, expected", [(1234, 1)])
def test_toy(value, expected):
    assert process(f"{value:n}") == expected
''')
    result = augment_corpus(corpus)
    assert additions(result) == []
    assert result['finite_inputs']['skipped']['locale_dependent_format']


def test_mutable_input_and_lossy_json_row_types_are_not_assumed_static(tmp_path):
    corpus = corpus_for(tmp_path, '''import pytest
@pytest.mark.parametrize("value, expected", [([1], 1), ((1,), 2)])
def test_toy(value, expected):
    assert process(f"{value}") == expected
''')
    result = augment_corpus(corpus)
    assert additions(result) == []
    assert result['finite_inputs']['skipped']['mutable_parameter_value']
    assert result['finite_inputs']['skipped']['row_type_not_preserved_by_corpus']


@pytest.mark.parametrize('expected, mutation, reason', [
    ('1', 'expected += 10', 'parameter_row_bindings_may_change'),
    ('[1]', 'expected.append(2)', 'mutable_parameter_row_value'),
])
def test_expected_row_value_cannot_drift_from_downstream_pre_value(tmp_path, expected, mutation, reason):
    corpus = corpus_for(tmp_path, '''import pytest
@pytest.mark.parametrize("value, expected", [("a", ''' + expected + ''')])
def test_toy(value, expected):
    ''' + mutation + '''
    assert process(f"{value}") == expected
''')
    result = augment_corpus(corpus)
    assert additions(result) == []
    assert result['finite_inputs']['skipped'][reason]


def test_format_width_and_expansion_budgets_are_enforced(tmp_path, monkeypatch):
    corpus = corpus_for(tmp_path, '''import pytest
@pytest.mark.parametrize("value, width, expected", [(1, 1000000, 1), (2, 2, 2)])
def test_toy(value, width, expected):
    assert process(f"{value:0{width}d}") == expected
''')
    result = augment_corpus(corpus)
    assert [row['literal_value'] for row in additions(result)] == ['02']
    assert result['finite_inputs']['skipped']['format_width_budget']
    monkeypatch.setattr(finite_inputs, 'MAX_EXPANSIONS', 1)
    result = augment_corpus(corpus)
    assert result['finite_inputs']['attempts'] == 1
    assert result['finite_inputs']['budget_exhausted']
