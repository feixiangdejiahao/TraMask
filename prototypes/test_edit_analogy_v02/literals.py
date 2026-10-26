"""Expose lexical variation inside every string without assuming its language.

Refinement is lossless: quote/escape/interpolation syntax stays in the original
tree. Content leaves become token sequences with exact byte provenance. This is
not a parser for protocols, paths, or programs contained in strings.
"""
from generic_composition.edits import tokens, token_sort
from generic_composition.terms import SourceTerm, Span, Term, render


_CONTENT = {'string_content', 'string_fragment', 'interpreted_string_literal_content',
            'raw_string_literal_content'}


def refine_strings(converted: SourceTerm) -> SourceTerm:
    positions = {}

    def refine(node, old_path, new_path):
        span = converted.spans[old_path]
        positions[new_path] = span
        if not node.children and node.kind in _CONTENT and isinstance(node.atom, str):
            pieces = tokens(node.atom)
            cursor, children = span.start_byte, []
            for index, piece in enumerate(pieces):
                end = cursor + len(piece.encode('utf-8'))
                positions[new_path + (index,)] = Span(cursor, end)
                children.append(Term('literal_token_' + token_sort(piece), piece))
                cursor = end
            if cursor != span.end_byte:
                raise ValueError('String token spans do not reconstruct the source')
            return Term(node.kind, None, tuple(children)) if children else node
        return Term(node.kind, node.atom, tuple(refine(child, old_path + (i,), new_path + (i,))
                                               for i, child in enumerate(node.children)))

    result = SourceTerm(refine(converted.term, (), ()), positions,
                        converted.source_path, converted.original_text)
    if render(result.term) != render(converted.term):
        raise ValueError('String refinement changed source bytes')
    return result
