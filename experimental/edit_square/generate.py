"""Independent lexical-square generator using the shared search/validation loop.

Each triple invokes only edit_square. Parsing reconstructs its output as a body
Term for shared novelty/binding checks; no tree-analogy view supplies candidates.
"""
import ast

from anchor_retrieval.syntax import Source, child, walk
from generic_composition.terms import BudgetExceeded, Term, from_source, render, subterms
from experimental.generic_v2.literals import refine_strings
from experimental.generic_v3.alignment import AlignmentResult
from experimental.generic_v3.generate import Budget, generate as _generate, gate_evidence as _evidence
from .core import edit_square


def _parse_body(code, language, indentation, max_nodes):
    if language == 'python':
        prefix = 'def _edit_square_body_():\n' + (indentation or '    ')
        kind = 'function_definition'
    elif language == 'go':
        prefix, kind = 'package square\nfunc _edit_square_body_() ', 'function_declaration'
    elif language == 'typescript':
        prefix, kind = 'function _edit_square_body_() ', 'function_declaration'
    else:
        raise ValueError('unsupported_language')
    text = prefix + code
    source = Source('square_body', text, language)
    if source.root.has_error:
        raise ValueError('body_syntax_error')
    if language == 'python':
        try:
            ast.parse(text)
        except SyntaxError:
            raise ValueError('body_syntax_error') from None
    function = next((n for n in walk(source.root) if n.type == kind), None)
    node = child(function, 'body') if function is not None else None
    start, end = len(prefix.encode()), len(text.encode())
    if node is None or not start <= node.start_byte <= node.end_byte <= end:
        raise ValueError('body_node_not_found')
    converted = refine_strings(from_source(source, node, max_nodes=max_nodes))
    # Parser body nodes can exclude surrounding trivia. Preserve every merged
    # byte while retaining the same grammar root used by the shared driver.
    before = source.data[start:node.start_byte].decode()
    after = source.data[node.end_byte:end].decode()
    children = ([Term('#trivia', before)] if before else []) + list(converted.term.children)
    children += [Term('#trivia', after)] if after else []
    term = Term(converted.term.kind, converted.term.atom, tuple(children))
    list(subterms(term, max_nodes=max_nodes))
    if render(term) != code:
        raise ValueError('body_bytes_not_preserved')
    return term


def compose_square(A, B, C, *, language, capsules=None, roles=None, max_nodes=1500, max_holes=32):
    square = edit_square(*(render(record['tree'].term) for record in (A, B, C)), max_tokens=max_nodes)
    base = {'checks': square['checks'], 'alignment': {}, 'has_shared_gap': bool(square.get('shared_insertion_points')),
            'kernel': 'lexical_edit_square_v1', 'unproved': square['unproved'],
            'source_interval_edits': square['edits'], 'diff_alignment': square['alignment'],
            'shared_insertion_points': square.get('shared_insertion_points', [])}
    if square['status'] != 'hypothesis':
        return [AlignmentResult('unsupported', provenance=dict(base, conflicts=square.get('conflicts', [])),
                                reason='edit_square:' + square['reason'])]
    results = []
    for merged in square['candidates']:
        order = merged['shared_insertion_order']
        witness = dict(base, gap_order='merge_' + '_'.join(order), merge_order=order)
        try:
            term = _parse_body(merged['code'], language, C.get('indentation', ''), max_nodes)
        except (ValueError, BudgetExceeded) as exc:
            reason = 'parsed_body_node_budget' if isinstance(exc, BudgetExceeded) else str(exc)
            results.append(AlignmentResult('unsupported', provenance=witness, reason='edit_square:' + reason))
            continue
        witness['checks'] = dict(witness['checks'], parsed_body_bytes_preserved=True)
        results.append(AlignmentResult('hypothesis', term, witness))
    return results


def generate(corpus, budget=Budget()):
    def compose(A, B, C, **options):
        return compose_square(A, B, C, language=corpus['language'], **options)
    result = _generate(corpus, budget, compose_views=compose)
    result['algorithm'] = 'lexical_test_edit_square_v1'
    result['counts']['attempted_merge_results'] = result['counts'].pop('attempted_orders')
    for candidate in result['candidates']:
        candidate['kind'] = 'lexical_test_edit_square'
        candidate['merge_order'] = candidate['provenance']['merge_order']
        candidate.pop('alignment', None)
        candidate['oracle'] = {
            'mode': 'merge_source_edits',
            'source_test_ids': list(dict.fromkeys([*candidate['source_test_ids'], candidate['base_test_id']])),
            'semantic_status': 'requires_admission'}
    for rule in result['rules']:
        rule['kind'] = 'lexical_test_edit_square'
    return result


def gate_evidence(corpus, generated, issue):
    evidence, candidates = _evidence(corpus, generated, issue)
    evidence['oracle_policy'] = (
        'Inputs and assertions are merged from both source-relative edits A->B and A->C. '
        'Fixed text originates in A and replacement text originates in B or C; the oracle is not solely copied from B. '
        'No expected value was inferred from execution. Judge every resulting assertion under the combined setup.')
    evidence['composition_policy'] = (
        'Only a language-independent lexical edit-square kernel constructed these proposals. '
        'Both source edits reconstruct exactly; disjoint source intervals are merged in the displayed insertion order. '
        'Diff correspondence is deterministic but not proved unique. This is not an aligned-residual guarantee '
        'or a proof of binding safety, effect independence, or oracle correctness.')
    evidence['merge_edits'] = {p['rule_id']: {
        'source_relative_edits': p['provenance']['source_interval_edits'],
        'insertion_order': p['merge_order'], 'checks': p['provenance']['checks']}
        for p in candidates}
    return evidence, candidates
