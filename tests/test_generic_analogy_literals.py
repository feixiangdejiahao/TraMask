import pytest

from anchor_retrieval.syntax import Source, walk
from prototypes.test_edit_analogy_v02.analogy import analogy
from prototypes.test_edit_analogy_v02.literals import refine_strings
from generic_composition.terms import from_source, render, subterms


@pytest.mark.parametrize('language,code', [
    ('python', 'x = "hello 世界 123"\ny = f"ready {x}!"'),
    ('python', 'x = r"a\\n/b 12"\ny = "a\\t12"'),
    ('go', 'package p\nvar x = "hello 世界 123"\nvar y = `f(3) + x`'),
    ('typescript', 'const x = "hello 世界 123"; const y = `ready ${x}!`;'),
])
def test_refinement_is_lossless_and_every_token_has_exact_source_span(language, code):
    source = Source('sample', code, language)
    original = from_source(source)
    refined = refine_strings(original)
    assert render(refined.term) == code
    token_count = 0
    for path, term in subterms(refined.term):
        if term.kind.startswith('literal_token_'):
            span = refined.spans[path]
            assert source.data[span.start_byte:span.end_byte].decode() == term.atom
            token_count += 1
    assert token_count > 1


@pytest.mark.parametrize('language,prefix', [
    ('python', 'x = '), ('go', 'package p\nvar x = '), ('typescript', 'const x = '),
])
def test_string_context_transport_uses_existing_tokens_without_domain_rules(language, prefix):
    def term(value):
        source = Source('sample', prefix + '"' + value + '"', language)
        literal = next(node for node in walk(source.root)
                       if node.type in {'string', 'interpreted_string_literal'})
        return refine_strings(from_source(source, literal)).term
    result = analogy(term('f(3)'), term('wrap(f(3))'), term('f(5)'))
    assert result.status == 'hypothesis'
    assert render(result.output) == '"wrap(f(5))"'
    assert result.provenance['unproved']
