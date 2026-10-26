"""A controlled mathematical ablation; source examples are invented."""
from anchor_retrieval.syntax import Source
from experimental.generic_v2.analogy import analogy as strict_analogy
from experimental.generic_v21.analogy import analogy as erasing_analogy
from generic_composition.terms import from_source, render


def term(code):
    return from_source(Source('invented.py', code, 'python')).term


A = 'assert f(3) == 6\n'
C = 'assert f(4) == 8\n'


def test_masked_expected_parameter_is_a_valid_erasing_rewrite():
    B = 'assert min(f(3), 5) == 5\n'
    terms = tuple(map(term, (A, B, C)))
    strict = strict_analogy(*terms)
    assert strict.status == 'unsupported'
    assert strict.reason == 'target_change_not_transportable'
    result = erasing_analogy(*terms)
    assert result.status == 'hypothesis'
    assert render(result.output) == 'assert min(f(4), 5) == 5\n'
    assert all(result.provenance['checks'].values())
    assert len(result.provenance['omitted_holes']) == 1
    # Under the independent toy contract f(x)=2*x, every source and D is true.
    assert 2 * 3 == 6 and min(2 * 3, 5) == 5 and 2 * 4 == 8
    assert min(2 * 4, 5) == 5


def test_erasing_rewrite_can_also_produce_a_wrong_constant_oracle():
    B = 'assert f(3) + 1 == 7\n'
    terms = tuple(map(term, (A, B, C)))
    assert strict_analogy(*terms).reason == 'target_change_not_transportable'
    result = erasing_analogy(*terms)
    assert result.status == 'hypothesis'
    assert render(result.output) == 'assert f(4) + 1 == 7\n'
    assert all(result.provenance['checks'].values())
    assert len(result.provenance['omitted_holes']) == 1
    assert 2 * 3 == 6 and 2 * 3 + 1 == 7 and 2 * 4 == 8
    assert 2 * 4 + 1 != 7
    assert 'oracle_validity' in result.provenance['unproved']


def test_erasing_every_target_change_still_fails_novelty():
    B = 'assert True\n'
    result = erasing_analogy(*(term(c) for c in (A, B, C)))
    assert result.status == 'unsupported'
    assert result.reason == 'no_new_combination'
