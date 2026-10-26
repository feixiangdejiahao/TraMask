"""Lossless representation probes with invented DSL/config/path strings."""
import pytest

from experimental.generic_v2.analogy import analogy
from experimental.generic_v4.balanced import balanced_tokens
from generic_composition.edits import tokens, token_sort
from generic_composition.terms import BudgetExceeded, Term, render, subterms


def flat(text):
    return Term('flat_sequence', children=tuple(Term('literal_token_' + token_sort(t), t)
                                               for t in tokens(text)))


def test_nested_dsl_arity_change_is_visible_with_grouping_but_not_flat_tokens():
    A, B, C = 'task(a)', 'wrap(task(a))', 'task(a,b)'
    baseline = analogy(*(flat(s) for s in (A, B, C)))
    assert baseline.status == 'unsupported'
    assert baseline.reason == 'target_change_not_transportable'
    result = analogy(*(balanced_tokens(s).term for s in (A, B, C)))
    assert result.status == 'hypothesis'
    assert render(result.output) == 'wrap(task(a,b))'
    assert all(result.provenance['checks'].values())
    assert 'oracle_validity' in result.provenance['unproved']


def test_config_record_extension_uses_the_same_delimiter_representation():
    A, B, C = 'mode={x:1}', 'memo(mode={x:1})', 'mode={x:1,y:2}'
    assert analogy(*(flat(s) for s in (A, B, C))).status == 'unsupported'
    result = analogy(*(balanced_tokens(s).term for s in (A, B, C)))
    assert result.status == 'hypothesis'
    assert render(result.output) == 'memo(mode={x:1,y:2})'


@pytest.mark.parametrize('text', [
    '  task([a, {b: "括号 ) ] }", c: 2}])\n',
    'task("quoted \\\" ( still quoted", \'single \\\' quote\')',
    r'escaped\(word\) and \[literal\]',
    'raw(`opaque ${value} [nested-looking]`)',
    '',
])
def test_exact_source_bytes_spans_quotes_escapes_and_unicode(text):
    start_byte = 71
    source = balanced_tokens(text, source_path='invented.data', start_byte=start_byte)
    assert render(source.term) == source.original_text == text
    assert source.source_path == 'invented.data'
    raw = text.encode()
    for path, node in subterms(source.term):
        span = source.spans[path]
        assert raw[span.start_byte - start_byte:span.end_byte - start_byte].decode() == render(node)
    assert source.spans[()].end_byte == start_byte + len(raw)


def test_path_growth_without_balanced_groups_still_exposes_the_limitation():
    A, B, C = '/root/item', '/prefix/root/item', '/root/item/child'
    result = analogy(*(balanced_tokens(s).term for s in (A, B, C)))
    assert result.status == 'unsupported'
    assert result.reason == 'target_change_not_transportable'


@pytest.mark.parametrize('text', ['task([x)]', 'task(x', 'task("unterminated)', 'ending\\'])
def test_unsupported_lexical_conventions_are_not_repaired(text):
    with pytest.raises(ValueError):
        balanced_tokens(text)


def test_balancing_is_not_a_grammar_or_semantic_validity_claim():
    # The representation retains even an application-invalid argument sequence.
    text = 'task(,a,,)'
    assert render(balanced_tokens(text).term) == text


def test_representation_budgets_are_explicit():
    with pytest.raises(BudgetExceeded):
        balanced_tokens('task(a,b)', max_nodes=2)
    with pytest.raises(BudgetExceeded):
        balanced_tokens('[[[x]]]', max_depth=2)


def test_existing_residual_slot_operator_can_align_unambiguous_token_sequences():
    from experimental.generic_v3.alignment import align_analogy
    from generic_composition.terms import SourceTerm
    texts = ('alpha|beta', 'prefix!alpha|beta', 'alpha|beta?suffix')
    views = [balanced_tokens(text) for text in texts]
    # A representation adapter only: v3's 'module' tag denotes its ordered-list
    # input. The units here are tokens, not parsed statements or DSL constructs.
    lists = [SourceTerm(Term('module', children=v.term.children), v.spans,
                        v.source_path, v.original_text) for v in views]
    keys = [list(v.term.children) for v in views]  # Exact lexical anchors only.
    result = align_analogy(*lists, anchor_keys=keys)
    assert result.status == 'hypothesis'
    assert render(result.output) == 'prefix!alpha|beta?suffix'
    assert all(result.provenance['checks'].values())
    assert result.provenance['checks']['C_residual_slots_preserved_exactly']
    assert 'oracle_validity' in result.provenance['unproved']


def test_repeated_path_separator_makes_exact_token_alignment_ambiguous():
    from experimental.generic_v3.alignment import align_analogy
    from generic_composition.terms import SourceTerm
    texts = ('/root/item', '/prefix/root/item', '/root/item/child')
    views = [balanced_tokens(text) for text in texts]
    lists = [SourceTerm(Term('module', children=v.term.children), v.spans,
                        v.source_path, v.original_text) for v in views]
    result = align_analogy(*lists, anchor_keys=[list(v.term.children) for v in views])
    assert result.status == 'unsupported'
    assert result.reason == 'ambiguous_alignment'
