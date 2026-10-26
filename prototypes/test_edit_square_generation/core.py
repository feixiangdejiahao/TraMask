"""Merge two source-relative lexical edits, with byte reconstruction witnesses.

The tokenizer is language-independent. One deterministic diff alignment is
chosen, without claiming unique correspondence, binding safety or a valid oracle.
"""
from collections import Counter
from difflib import SequenceMatcher
import re


_TOKEN = re.compile(r'\s+|\w+|[^\w\s]', re.UNICODE)


def _tokens(text):
    parts = _TOKEN.findall(text)
    if ''.join(parts) != text:
        raise ValueError('tokenization_not_lossless')
    boundaries = [0]
    for token in parts:
        boundaries.append(boundaries[-1] + len(token.encode('utf-8')))
    return parts, boundaries


def _diff(source, target, A, T):
    tokens_A, bytes_A = A
    tokens_T, bytes_T = T
    edits = []
    for kind, a, b, c, d in SequenceMatcher(a=tokens_A, b=tokens_T, autojunk=False).get_opcodes():
        if kind == 'equal':
            continue
        start, end = bytes_A[a], bytes_A[b]
        replacement = ''.join(tokens_T[c:d])
        edits.append({'start_byte': start, 'end_byte': end,
                      'before': source.encode('utf-8')[start:end].decode('utf-8'),
                      'replacement': replacement, 'source_tokens': [a, b],
                      'target_bytes': [bytes_T[c], bytes_T[d]], 'target_tokens': [c, d]})
    return edits


def _apply(source, edits, order):
    """Boundary insertions precede replacements starting at the same byte."""
    side_order = {name: index for index, name in enumerate(order)}
    ordered = sorted(edits, key=lambda pair: (
        pair[1]['start_byte'], pair[1]['end_byte'] != pair[1]['start_byte'], side_order[pair[0]]))
    data, cursor, output = source.encode('utf-8'), 0, []
    for _, edit in ordered:
        start, end = edit['start_byte'], edit['end_byte']
        if start < cursor:
            raise ValueError('overlapping_edits')
        if data[start:end].decode('utf-8') != edit['before']:
            raise ValueError('source_interval_mismatch')
        output.extend((data[cursor:start], edit['replacement'].encode('utf-8')))
        cursor = end
    output.append(data[cursor:])
    return b''.join(output).decode('utf-8')


def _conflict(left, right):
    a, b = left['start_byte'], left['end_byte']
    c, d = right['start_byte'], right['end_byte']
    if a < b and c < d and max(a, c) < min(b, d):
        return 'overlapping_replacements'
    if a == b and c < a < d or c == d and a < c < b:
        return 'insertion_inside_replacement'
    return None


def edit_square(A, B, C, *, max_tokens=4096, max_bytes=100000):
    """Return at most two D programs sharing the source-relative edit square.

    A->B and A->C must each reconstruct exactly. Cross-side replacements cannot
    overlap; insertions may touch replacement boundaries but not their interior.
    At shared insertion points, use B-then-C everywhere or C-then-B everywhere.
    These are two bounded merge orders, not all possible interleavings.
    """
    if any(not isinstance(s, str) for s in (A, B, C)):
        raise TypeError('edit_square expects three source strings')
    if any(type(n) is not int or n < 1 for n in (max_tokens, max_bytes)):
        raise ValueError('budgets must be positive integers')
    result = {'status': 'unsupported', 'candidates': [], 'edits': {}, 'checks': {},
              'alignment': {'algorithm': 'difflib.SequenceMatcher', 'autojunk': False,
                            'uniqueness': 'not_checked', 'tokenizer': r'\s+|\w+|[^\w\s]'},
              'unproved': ['alignment_semantics', 'syntax_validity', 'bindings_and_capture',
                           'effects_and_aliases', 'oracle_validity']}
    if any(len(s.encode('utf-8')) > max_bytes for s in (A, B, C)):
        return dict(result, reason='byte_budget')
    tokenized = [_tokens(s) for s in (A, B, C)]
    if any(len(tokens) > max_tokens for tokens, _ in tokenized):
        return dict(result, reason='token_budget')
    result['alignment']['repeated_source_token_kinds'] = sum(n > 1 for n in Counter(tokenized[0][0]).values())
    if A == B or A == C:
        return dict(result, reason='unchanged_side')
    if B == C:
        return dict(result, reason='identical_sides')
    result['edits'] = {'B': _diff(A, B, tokenized[0], tokenized[1]),
                       'C': _diff(A, C, tokenized[0], tokenized[2])}
    result['checks'] = {f'A_edits_equal_{side}': _apply(A, [(side, e) for e in result['edits'][side]], (side,)) == text
                        for side, text in (('B', B), ('C', C))}
    if not all(result['checks'].values()):
        return dict(result, reason='source_reconstruction_failed')
    conflicts, shared_points = [], set()
    for i, left in enumerate(result['edits']['B']):
        for j, right in enumerate(result['edits']['C']):
            reason = _conflict(left, right)
            if reason:
                conflicts.append({'B_edit': i, 'C_edit': j, 'reason': reason})
            if left['start_byte'] == left['end_byte'] == right['start_byte'] == right['end_byte']:
                shared_points.add(left['start_byte'])
    if conflicts:
        return dict(result, reason='conflicting_source_intervals', conflicts=conflicts)
    result['shared_insertion_points'] = sorted(shared_points)
    edits = [(side, edit) for side in ('B', 'C') for edit in result['edits'][side]]
    seen = {A, B, C}
    orders = [('B', 'C'), ('C', 'B')] if shared_points else [('B', 'C')]
    for order in orders:
        output = _apply(A, edits, order)
        if output not in seen:
            seen.add(output)
            result['candidates'].append({'code': output, 'shared_insertion_order': list(order)})
    if not result['candidates']:
        return dict(result, reason='no_new_combination')
    return dict(result, status='hypothesis', reason=None)
