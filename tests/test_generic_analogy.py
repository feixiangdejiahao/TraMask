"""Mechanical analogies on synthetic terms, without repositories or execution."""
from anchor_retrieval.syntax import Source
from generic_composition.terms import Hole, Term, from_source, render, substitute, subterms
from prototypes.test_edit_analogy_v02.analogy import analogy


def literal(value):
    return Term('integer', str(value))


def call(name, *args):
    return Term('call', name, args)


def eq(actual, expected):
    return Term('assert_equal', None, (actual, expected))


def vector(value):
    return Term('list', None, (value,))


def test_input_and_oracle_container_changes_are_transported_together():
    A = eq(call('f', literal(3)), literal(6))
    B = eq(call('f', vector(literal(3))), vector(literal(6)))
    C = eq(call('f', literal(5)), literal(10))
    result = analogy(A, B, C)
    assert result.status == 'hypothesis'
    assert result.output == eq(call('f', vector(literal(5))), vector(literal(10)))
    assert all(result.provenance['checks'].values())
    assert substitute(result.after_pattern, result.provenance['source_substitutions']) == B
    assert substitute(result.before_pattern, result.provenance['target_substitutions']) == C
    assert 'oracle_validity' in result.provenance['unproved']


def test_real_python_tokens_roundtrip_without_losing_punctuation_or_spaces():
    def parsed(code):
        return from_source(Source('toy.py', code, 'python')).term
    A = parsed('assert f(3) == 6\n')
    B = parsed('assert f([3]) == [6]\n')
    C = parsed('assert f(5) == 10\n')
    result = analogy(A, B, C)
    assert result.status == 'hypothesis'
    assert render(result.output) == 'assert f([5]) == [10]\n'


def test_stronger_observation_comes_from_B_and_expected_binding_from_C_input():
    weak = Term('assert_nonnull', 'box')
    A = Term('test', None, (call('put', literal(4)), weak))
    B = Term('test', None, (call('put', literal(4)), eq(call('peek'), literal(4))))
    C = Term('test', None, (call('put', literal(9)), weak))
    result = analogy(A, B, C)
    assert result.status == 'hypothesis'
    assert result.output == Term('test', None, (call('put', literal(9)), eq(call('peek'), literal(9))))
    assert len({row['hole'] for row in result.provenance['transfers']}) == 1
    inserted_oracle = next(row for row in result.provenance['transfers'] if row['output_path'] == [1, 1])
    assert inserted_oracle['c_paths'] == [[0, 0]]


def test_equal_source_values_with_different_target_roles_are_ambiguous():
    A = eq(call('f', literal(1)), literal(1))
    B = eq(call('f', vector(literal(1))), vector(literal(1)))
    C = eq(call('f', literal(2)), literal(7))
    result = analogy(A, B, C)
    assert result.status == 'unsupported' and result.output is None
    assert result.reason == 'ambiguous_source_subtree'


def test_unchanged_occurrence_also_prevents_silent_oracle_rewrite():
    A = eq(call('f', literal(1)), literal(1))
    B = eq(call('f', vector(literal(1))), vector(literal(1)))
    C = eq(call('f', literal(2)), literal(1))
    result = analogy(A, B, C)
    assert result.status == 'unsupported'
    assert result.reason == 'ambiguous_source_subtree'


def test_explicit_role_correspondences_disambiguate_same_literal():
    A = eq(call('f', literal(1)), literal(1))
    B = eq(call('f', vector(literal(1))), vector(literal(1)))
    C = eq(call('f', literal(2)), literal(7))
    roles = ({(0, 0): 'input', (1,): 'oracle'},
             {(0, 0, 0): 'input', (1, 0): 'oracle'},
             {(0, 0): 'input', (1,): 'oracle'})
    result = analogy(A, B, C, roles=roles)
    assert result.output == eq(call('f', vector(literal(2))), vector(literal(7)))


def test_identifier_transport_requires_given_binding_labels_not_spelling():
    x, y = Term('identifier', 'x'), Term('identifier', 'y')
    A, C = call('f', x), call('f', y)
    B = call('f', Term('attribute', None, (x, Term('identifier', 'x'))))
    assert analogy(A, B, C).reason == 'unresolved_identifier_binding'
    result = analogy(A, B, C, roles=(
        {(0,): 'binding0'},
        {(0, 0): 'binding0', (0, 1): 'property_name'},
        {(0,): 'binding0'},
    ))
    assert result.output == call('f', Term('attribute', None, (y, Term('identifier', 'x'))))
    assert result.provenance['explicit_distinct_B_roles'] == [[0, 1]]


def test_conflicting_given_bindings_are_rejected():
    A, B, C = call('f', literal(1)), call('f', vector(literal(1))), call('f', literal(2))
    result = analogy(A, B, C, roles=({(0,): 'left'}, {(0, 0): 'left'}, {(0,): 'right'}))
    assert result.reason == 'inconsistent_correspondence_labels'


def test_no_subject_language_needed_for_explicit_token_terms():
    def text(value):
        return Term('literal_tokens', None, (Term('token', value),))
    A = eq(call('parse', text('alpha')), literal(1))
    B = eq(call('parse', Term('literal_tokens', None, (
        Term('token', '['), Term('token', 'alpha'), Term('token', ']')))), literal(1))
    C = eq(call('parse', text('beta')), literal(1))
    result = analogy(A, B, C)
    assert result.output == eq(call('parse', Term('literal_tokens', None, (
        Term('token', '['), Term('token', 'beta'), Term('token', ']')))), literal(1))
    assert result.status == 'hypothesis'


def test_dropped_target_changes_and_noop_are_explicitly_unsupported():
    A = eq(call('f', literal(1)), literal(2))
    C = eq(call('f', literal(3)), literal(6))
    B = eq(call('f', vector(literal(1))), literal(99))
    assert analogy(A, B, C).reason == 'target_change_not_transportable'
    assert analogy(A, A, C).reason == 'no_edit_or_no_target_change'
    assert analogy(A, B, A).reason == 'no_edit_or_no_target_change'


def test_budget_and_ground_term_checks_are_deterministic():
    A, B, C = call('f', literal(1)), call('f', vector(literal(1))), call('f', literal(2))
    assert analogy(A, B, C, max_nodes=1).reason == 'syntax_budget_exceeded'
    assert analogy(A, B, C, max_holes=0).reason == 'syntax_budget_exceeded'
    assert analogy(call('f', Hole('any', 0)), B, C).reason == 'non_ground_source'
    assert analogy(A, B, C) == analogy(A, B, C)
    result = analogy(A, B, C)
    assert all(not isinstance(n, Hole) for _, n in subterms(result.output))
