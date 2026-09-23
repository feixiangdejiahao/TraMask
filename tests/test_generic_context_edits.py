"""Mechanical context-learning checks without subject repositories or oracles."""
import json

import pytest

from anchor_retrieval.syntax import Source, walk
from generic_composition.context_edits import ContextEdit, learn_context_edits
from generic_composition.corpus import expression
from generic_composition.terms import BudgetExceeded, Hole, from_source, subterms


def expr(text, *, language='python'):
    programs = {'python': 'result = ' + text + '\n',
                'go': 'package demo\nfunc run() { _ = ' + text + ' }\n',
                'typescript': 'const result = ' + text + ';\n'}
    source = Source('synthetic.' + {'python': 'py', 'go': 'go', 'typescript': 'ts'}[language],
                    programs[language], language)
    assert not source.root.has_error
    matches = [n for n in walk(source.root) if source.text(n) == text]
    assert matches
    return source, matches[-1]


def apply_first(before, after, target, **kwargs):
    edits = learn_context_edits(expr(before), expr(after))
    assert edits
    applied = edits[0].apply(expr(target), **kwargs)
    assert applied is not None
    return edits[0], applied


def test_whole_call_is_a_carrier_inside_learned_wrapper():
    edit, applied = apply_first('read(x)', 'store(read(x))', 'compute(y, z)')
    assert isinstance(edit.before, Hole)
    assert applied.text == 'store(compute(y, z))'
    assert applied.unbound_free_names == ('store',)
    assert applied.introduced_names == ('store',)
    assert applied.provenance['claim'] == 'syntactic_reconstruction_only'
    assert applied.provenance['target']['start_byte'] == len('result = ')
    assert applied.provenance['carriers'][0]['text'] == 'compute(y, z)'
    edit.check_reconstruction()


def test_unwrapper_and_changed_wrapper_keep_target_expression():
    _, unwrapped = apply_first('wrap(x)', 'x', 'wrap(work(y))')
    assert unwrapped.text == 'work(y)'
    edit, applied = apply_first('left(x)', 'right(x)', 'left(work(y))', available_names={'right'})
    assert applied.text == 'right(work(y))'
    assert applied.unbound_free_names == ()
    assert edit.apply(expr('unrelated(work(y))')) is None


@pytest.mark.parametrize('language', ['python', 'go', 'typescript'])
def test_method_receiver_can_be_carrier_while_member_name_stays_literal(language):
    edit = learn_context_edits(expr('make(x)', language=language),
                               expr('make(x).finish()', language=language))[0]
    assert isinstance(edit.before, Hole)
    applied = edit.apply(expr('produce(y)', language=language))
    assert applied.text == 'produce(y).finish()'
    assert applied.unbound_free_names == ()
    assert 'finish' not in applied.introduced_names


def test_multi_hole_parameter_reordering_preserves_correlations():
    edit, applied = apply_first('f(x, y)', 'g(y, x)', 'f(a + 1, b[0])')
    assert len(edit.source_bindings) == 2
    assert applied.text == 'g(b[0], a + 1)'
    assert applied.unbound_free_names == ('g',)
    assert applied.provenance['carrier_occurrence_changes'] == []


def test_repeated_carrier_requires_equal_target_subtrees():
    edit, applied = apply_first('f(x, x)', 'g(x)', 'f(value, value)')
    assert len(edit.source_bindings) == 1
    assert applied.text == 'g(value)'
    assert edit.apply(expr('f(first, second)')) is None
    counts = applied.provenance['carrier_occurrence_changes'][0]
    assert len(counts['before']) == 2 and len(counts['after']) == 1


def test_duplication_is_reported_as_syntax_not_safety_or_purity():
    _, applied = apply_first('x', 'join(x, x)', 'effect()')
    assert applied.text == 'join(effect(), effect())'
    counts = applied.provenance['carrier_occurrence_changes'][0]
    assert len(counts['before']) == 1 and len(counts['after']) == 2
    assert 'capture_and_scope_unresolved' in applied.provenance['binding_precision']


def test_callee_and_property_spelling_are_not_carrier_holes():
    edit, applied = apply_first('f(f)', 'g(f)', 'f(value)')
    assert applied.text == 'g(value)'
    assert edit.apply(expr('other(value)')) is None
    # The only common name is a property. No expression carrier exists.
    assert learn_context_edits(expr('left.value'), expr('right.value')) == []
    # Parentheses do not turn the callee identifier into a value carrier.
    assert learn_context_edits(expr('(f)(left)'), expr('(f)(right)')) == []
    # Keys and strings remain intact even when spelling equals the carrier.
    edits = learn_context_edits(expr("f(x, {'x': x})"), expr("g(x, {'x': x})"))
    applied = [result for edit in edits if (result := edit.apply(expr("f(y, {'x': y})")))]
    assert applied and all(result.text == "g(y, {'x': y})" for result in applied)


@pytest.mark.parametrize('language,before,after,target,expected', [
    ('python', 'get(x)', 'wrap(get(x))', 'other(2)', 'wrap(other(2))'),
    ('go', 'get(x)', 'wrap(get(x))', 'other(2)', 'wrap(other(2))'),
    ('typescript', 'get(x)', 'wrap(get(x))', 'other(2)', 'wrap(other(2))'),
])
def test_corpus_expressions_and_source_nodes_share_exact_reconstruction(language, before, after, target, expected):
    a, b, c = (expr(t, language=language) for t in (before, after, target))
    direct = learn_context_edits(a, b)[0]
    corpus_edit = learn_context_edits(expression(*a), expression(*b))[0]
    assert direct.fingerprint == corpus_edit.fingerprint
    assert corpus_edit.apply(expression(*c)).text == expected
    assert corpus_edit.source_before['start_byte'] == a[1].start_byte
    assert corpus_edit.source_before['text'] == before
    corpus_edit.check_reconstruction()


def test_trivia_and_unicode_roundtrip_in_corpus_adapter():
    a, b = expr('fetch("雪",  x)'), expr('wrap( fetch("雪",  x) )')
    edit = learn_context_edits(expression(*a), expression(*b))[0]
    assert edit.apply(expression(*a)).text == 'wrap( fetch("雪",  x) )'
    restored = ContextEdit.from_dict(json.loads(json.dumps(edit.as_dict())))
    assert restored.as_dict() == edit.as_dict()
    assert restored.apply(expr('next("λ")')).text == 'wrap( next("λ") )'
    altered = edit.as_dict()
    altered['source_after'] = dict(altered['source_after'], text='tampered')
    with pytest.raises(ValueError, match='reconstruct'):
        ContextEdit.from_dict(altered)


def test_terms_and_sourceterms_are_accepted_without_inventing_bindings():
    a, b = (from_source(*expr(t)) for t in ('f(x)', 'g(x)'))
    for left, right in ((a, b), (a.term, b.term)):
        edit = learn_context_edits(left, right)[0]
        applied = edit.apply(from_source(*expr('f(y)')))
        assert applied.text == 'g(y)'
        assert applied.unbound_free_names == ('g',)


def test_noop_unrelated_sources_and_explicit_budgets():
    assert learn_context_edits(expr('same(x)'), expr('same(x)')) == []
    assert learn_context_edits(expr('left(x)'), expr('right(y)')) == []
    with pytest.raises(BudgetExceeded):
        learn_context_edits(expr('call(x)'), expr('wrap(call(x))'), max_nodes=2)
    with pytest.raises(ValueError, match='positive'):
        learn_context_edits(expr('x'), expr('wrap(x)'), max_candidates=0)
    one = learn_context_edits(expr('f(x, y)'), expr('g(y, x)'), max_candidates=1)
    assert len(one) == 1
    assert len(one[0].source_bindings) == 2
    limited = learn_context_edits(expr('f(x, y)'), expr('g(y, x)'), max_holes=1)
    assert all(len(e.source_bindings) == 1 for e in limited)


def test_deterministic_provenance_and_both_source_reconstructions():
    a, b = expr('first(a, b, a)'), expr('second(b, a)')
    edits = learn_context_edits(a, b)
    assert [e.as_dict() for e in edits] == [e.as_dict() for e in learn_context_edits(a, b)]
    for edit in edits:
        edit.check_reconstruction()
        assert edit.apply(a).text == b[0].text(b[1])
        assert all(isinstance(n, Hole) or n.kind != 'unknown_relation'
                   for _, n in subterms(edit.before))
