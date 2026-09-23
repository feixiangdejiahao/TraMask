"""Statement-sequence composition on standalone invented source only."""
import ast
import pytest

from anchor_retrieval.syntax import Source, child, walk
from experimental.generic_v3.alignment import align_analogy
from generic_composition.terms import from_source, render


def term(code, language='python'):
    return from_source(Source('sample', code, language))


def test_extra_target_setup_survives_source_operation_and_oracle_transport():
    A = 'x = f(1)\nassert x == 2\n'
    B = 'x = f(1)\ncheckpoint(x)\nassert x == 2\n'
    C = 'arg = 3\nx = f(arg)\nassert x == 6\n'
    result = align_analogy(*map(term, (A, B, C)))
    assert result.status == 'hypothesis', result
    assert render(result.output) == 'arg = 3\nx = f(arg)\ncheckpoint(x)\nassert x == 6\n'
    assert all(result.provenance['checks'].values())
    assert result.provenance['alignment'] == {'A_to_B': [0, 2], 'A_to_C': [1, 2]}
    ast.parse(render(result.output))


def test_same_gap_additions_offer_two_internal_order_preserving_hypotheses():
    A = term('x = f(1)\nassert x == 2\n')
    B = term('x = f(1)\ncheckpoint(x)\nassert x == 2\n')
    C = term('x = f(3)\nsnapshot(x)\nassert x == 6\n')
    first = align_analogy(A, B, C)
    second = align_analogy(A, B, C, order='edit_first')
    assert first.status == second.status == 'hypothesis'
    assert render(first.output) == 'x = f(3)\nsnapshot(x)\ncheckpoint(x)\nassert x == 6\n'
    assert render(second.output) == 'x = f(3)\ncheckpoint(x)\nsnapshot(x)\nassert x == 6\n'
    assert {'effects', 'bindings_and_capture'} <= set(first.provenance['unproved'])


def test_equal_repeated_residual_statements_are_preserved_as_two_occurrences():
    A = term('x = f(1)\nassert x == 2\n')
    B = term('x = f(1)\ncheckpoint(x)\nassert x == 2\n')
    C = term('prepare()\nprepare()\nx = f(3)\nassert x == 6\n')
    result = align_analogy(A, B, C)
    assert result.status == 'hypothesis'
    assert render(result.output).count('prepare()') == 2
    assert [r['statement'] for r in result.provenance['source_occurrences']['C']] == [0, 1, 2, 3]


def test_ambiguous_repeated_producer_does_not_get_a_greedy_anchor():
    result = align_analogy(term('x = f(1)\nassert x == 2\n'),
                           term('x = f(1)\ncheckpoint(x)\nassert x == 2\n'),
                           term('first = f(3)\nx = f(3)\nassert x == 6\n'))
    assert result.status == 'unsupported' and result.reason == 'ambiguous_alignment'


def test_control_flow_body_is_not_flattened_into_an_outer_anchor():
    result = align_analogy(term('x = f(1)\nassert x == 2\n'),
                           term('x = f(1)\ncheckpoint(x)\nassert x == 2\n'),
                           term('if ready:\n    x = f(3)\nassert x == 6\n'))
    assert result.status == 'unsupported' and result.reason == 'missing_anchor'


def test_comments_and_nested_scope_indentation_roundtrip_exactly():
    def body(code):
        source = Source('sample.py', 'def test_example():\n' + code, 'python')
        function = next(n for n in walk(source.root) if n.type == 'function_definition')
        return from_source(source, child(function, 'body'))
    result = align_analogy(body('    x = f(1)  # original\n    assert x == 2\n'),
                           body('    x = f(1)  # original\n    checkpoint(x)\n    assert x == 2\n'),
                           body('    arg = 3  # setup\n    x = f(arg)  # original\n    assert x == 6\n'))
    assert result.status == 'hypothesis'
    assert render(result.output) == 'arg = 3  # setup\n    x = f(arg)  # original\n    checkpoint(x)\n    assert x == 6'
    assert all(result.provenance['checks'].values())


def test_statement_budget_and_missing_anchor_report_structure_limits():
    A = term('x = f(1)\nassert x == 2\n')
    B = term('x = f(1)\ncheckpoint(x)\nassert x == 2\n')
    C = term('arg = 3\nx = f(arg)\nassert x == 6\n')
    assert align_analogy(A, B, C, max_statements=2).reason == 'statement_budget'
    assert align_analogy(A, B, term('x = other(3)\nassert x == 6\n')).reason == 'missing_anchor'


@pytest.mark.parametrize('language,prefix,A,B,C,body_kind,expected', [
    ('go', 'package p\nfunc TestExample(){',
     'x := f(1); check(x, 2)', 'x := f(1); checkpoint(x); check(x, 2)',
     'arg := 3; x := f(arg); check(x, 6)', 'block',
     '{arg := 3; x := f(arg); checkpoint(x); check(x, 6)}'),
    ('typescript', 'function testExample(){',
     'const x = f(1); check(x, 2);', 'const x = f(1); checkpoint(x); check(x, 2);',
     'const arg = 3; const x = f(arg); check(x, 6);', 'statement_block',
     '{const arg = 3; const x = f(arg); checkpoint(x); check(x, 6);}'),
])
def test_direct_braced_statement_lists_preserve_delimiters(language,prefix,A,B,C,body_kind,expected):
    def body(text):
        source = Source('sample', prefix + text + '}', language)
        node = next(n for n in walk(source.root) if n.type == body_kind)
        return from_source(source, node)
    result = align_analogy(*[body(t) for t in (A, B, C)])
    assert result.status == 'hypothesis', result
    assert render(result.output) == expected
    assert all(result.provenance['checks'].values())
