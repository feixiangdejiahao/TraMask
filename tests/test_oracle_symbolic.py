"""Observed-value rewriting with invented equations; no subject execution."""
import pytest

from prototypes.oracle_value_analysis.core import Equation, derive


A, C = Equation('f(3)', '3'), Equation('f(8)', '8')


def test_observed_context_computes_new_oracle_instead_of_copying_B_constant():
    result = derive(A, Equation('f(3) + 1', '4'), C)
    assert result.status == 'conditional'
    assert result.actual == 'f(8) + 1' and result.expected == '9'
    assert result.context == 'observed_value + 1'
    assert all(result.checks.values())
    assert 'carrier_has_builtin_value_semantics' in result.premises


def test_same_literal_value_in_input_and_context_is_not_a_shared_hole():
    result = derive(A, Equation('f(3) + 3', '6'), C)
    assert result.actual == 'f(8) + 3'
    assert result.expected == '11'  # Replacing every 3 with 8 would give 16.


@pytest.mark.parametrize('actual,expected,want_actual,want_expected', [
    ('[f(3), 1]', '[3, 1]', '[f(8), 1]', '[8, 1]'),
    ('([f(3)], "tag")', '([3], "tag")', "([f(8)], 'tag')", "([8], 'tag')"),
    ('-(f(3) * 2)', '-6', '-(f(8) * 2)', '-16'),
    ('(f(3) + 1) // 2', '2', '(f(8) + 1) // 2', '4'),
])
def test_pure_operators_and_container_contexts_use_one_algorithm(actual, expected, want_actual, want_expected):
    result = derive(A, Equation(actual, expected), C)
    assert result.status == 'conditional'
    assert result.actual == want_actual and result.expected == want_expected
    assert all(result.checks.values())


def test_sequence_value_contexts_are_interpreted_without_subject_calls():
    a, c = Equation('read("a")', '[1]'), Equation('read("b")', '[2, 3]')
    result = derive(a, Equation('read("a") + [4]', '[1, 4]'), c)
    assert result.status == 'conditional'
    assert result.expected == '[2, 3, 4]'


def test_non_linear_carrier_and_equal_literal_roles_are_explicitly_unsupported():
    result = derive(A, Equation('f(3) + f(3)', '6'), C)
    assert result.status == 'unsupported' and result.reason == 'carrier_not_unique'
    ambiguous = derive(Equation('3', '3'), Equation('3 + 3', '6'), Equation('8', '8'))
    assert ambiguous.reason == 'carrier_not_unique'


def test_unknown_call_is_not_executed_to_obtain_the_expected_value():
    result = derive(A, Equation('f(3) + side_effect()', '4'), C)
    assert result.status == 'unsupported'
    assert result.reason == 'unsupported_context_node:Call'


def test_a_context_must_explain_the_existing_B_oracle_first():
    result = derive(A, Equation('f(3) + 1', '99'), C)
    assert result.status == 'unsupported'
    assert result.reason == 'source_expected_not_explained'
    assert result.checks['B_expected_recomputed'] is False


def test_plain_python_equality_does_not_discharge_builtin_value_premise():
    class LooksLikeEight:
        def __eq__(self, other):
            return other == 8

        def __add__(self, other):
            return 100

    result = derive(A, Equation('f(3) + 1', '4'), C)
    value = LooksLikeEight()
    assert value == 8 and value + 1 != 9
    assert result.expected == '9'
    assert result.status == 'conditional'
    assert 'carrier_has_builtin_value_semantics' in result.premises


def test_unknown_names_and_partial_operators_do_not_become_ground_oracles():
    result = derive(A, Equation('f(3) + offset', '4'), C)
    assert result.reason == 'unsupported_context_node:Name'
    zero = derive(A, Equation('1 // (f(3) - 8)', '-1'), C)
    assert zero.reason == 'undefined_constant_operation'


def test_literal_type_and_size_limits_are_explicit():
    boolean = derive(A, Equation('f(3) - 2', 'True'), C)
    assert boolean.reason == 'source_expected_not_explained'
    large = derive(A, Equation('[f(3)] * 20', '[3] * 20'), C, max_items=10)
    assert large.status == 'unsupported' and large.reason == 'constant_value_budget'
    floating = derive(A, Equation('f(3) + 0.5', '3.5'), C)
    assert floating.reason == 'unsupported_constant_type'


def test_missing_and_identity_contexts_do_not_propose_new_tests():
    assert derive(A, Equation('g(3) + 1', '4'), C).reason == 'carrier_missing'
    assert derive(A, A, C).reason == 'identity_context'
