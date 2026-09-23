"""Lossless delimiter grouping, not a parser for the text's language.

Only (), [] and {} nesting and backslash-escaped quote spans are recognized.
Quoted spans are opaque: no interpolation, comment, regex, protocol, path or
embedded-language semantics are inferred. Input is the exact text to represent;
this function does not decode a host language's string literal escapes.

Grouping can expose reusable syntax subtrees when flat-token lengths differ.
Balanced delimiters do not establish well-formedness or oracle validity. Invalid
or ambiguous-to-this-lexer text is explicitly unsupported, never repaired.
"""
from __future__ import annotations

from dataclasses import dataclass

from generic_composition.edits import tokens, token_sort
from generic_composition.terms import BudgetExceeded, SourceTerm, Span, Term, render


_PAIRS = {'(': ')', '[': ']', '{': '}'}
_QUOTES = {'"', "'", '`'}
_SPECIAL = set(_PAIRS) | set(_PAIRS.values()) | _QUOTES | {'\\'}


@dataclass(frozen=True)
class _Piece:
    term: Term
    start: int
    end: int
    children: tuple['_Piece', ...] = ()


def balanced_tokens(text: str, *, source_path: str = '', start_byte: int = 0,
                    max_nodes: int = 2048, max_depth: int = 64) -> SourceTerm:
    """Return a byte-exact token tree or raise ValueError/BudgetExceeded.

    ``start_byte`` embeds all returned spans in the caller's source coordinates.
    All leaves, including whitespace, delimiters, quotes and escape sequences,
    retain the original bytes. Matching quote characters and their contents form
    one opaque leaf; backslash escapes the following character inside/outside a
    quoted span. No subject code is parsed beyond these generic conventions.
    """
    if type(start_byte) is not int or start_byte < 0:
        raise ValueError('start_byte must be a nonnegative integer')
    if type(max_nodes) is not int or max_nodes < 1 or type(max_depth) is not int or max_depth < 0:
        raise ValueError('invalid representation budget')
    offsets = [start_byte]
    for char in text:
        offsets.append(offsets[-1] + len(char.encode('utf-8')))
    cursor, count = 0, 0

    def piece(kind, a, b, children=()):
        nonlocal count
        count += 1
        if count > max_nodes:
            raise BudgetExceeded('Balanced token node budget exceeded')
        term = Term(kind, None, tuple(c.term for c in children)) if children else Term(kind, text[a:b])
        return _Piece(term, a, b, tuple(children))

    def sequence(close=None, depth=0):
        nonlocal cursor
        if depth > max_depth:
            raise BudgetExceeded('Balanced delimiter depth exceeded')
        items = []
        while cursor < len(text):
            char, begin = text[cursor], cursor
            if char in _PAIRS.values():
                if char == close:
                    return items
                raise ValueError(f'unmatched_delimiter_at_byte:{offsets[cursor]}')
            if char in _PAIRS:
                cursor += 1
                opening = piece('delimiter', begin, cursor)
                inside = sequence(_PAIRS[char], depth + 1)
                if cursor == len(text):
                    raise ValueError(f'unclosed_delimiter_at_byte:{offsets[begin]}')
                closing = piece('delimiter', cursor, cursor + 1)
                cursor += 1
                items.append(piece('balanced_group_' + char + _PAIRS[char], begin, cursor,
                                   [opening, *inside, closing]))
            elif char in _QUOTES:
                quote = char
                cursor += 1
                while cursor < len(text) and text[cursor] != quote:
                    if text[cursor] == '\\':
                        cursor += 1
                    cursor += 1
                if cursor >= len(text):
                    raise ValueError(f'unclosed_quote_at_byte:{offsets[begin]}')
                cursor += 1
                items.append(piece('quoted_token', begin, cursor))
            elif char == '\\':
                if cursor + 1 == len(text):
                    raise ValueError(f'trailing_escape_at_byte:{offsets[begin]}')
                cursor += 2
                items.append(piece('escaped_token', begin, cursor))
            else:
                while cursor < len(text) and text[cursor] not in _SPECIAL:
                    cursor += 1
                position = begin
                for value in tokens(text[begin:cursor]):
                    end = position + len(value)
                    items.append(piece('literal_token_' + token_sort(value), position, end))
                    position = end
        if close is not None:
            raise ValueError(f'unclosed_delimiter_at_byte:{offsets[cursor]}')
        return items

    root = piece('balanced_sequence', 0, len(text), sequence())
    spans = {}

    def record(node, path):
        spans[path] = Span(offsets[node.start], offsets[node.end])
        for i, nested in enumerate(node.children):
            record(nested, path + (i,))

    record(root, ())
    result = SourceTerm(root.term, spans, source_path, text)
    if render(result.term) != text:
        raise AssertionError('Lossless representation invariant failed')
    return result
