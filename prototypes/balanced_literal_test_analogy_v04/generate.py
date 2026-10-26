"""v3 search/composition with one isolated literal-representation substitution.

Only the literal refinement callback changes. Search, composition, budgets,
mechanical checks and semantic admission are inherited from the v3 driver.
"""
from collections import Counter

from prototypes.test_edit_analogy_v02.literals import refine_strings as flat_strings
from prototypes.statement_aligned_test_analogy_v03 import generate as _v3
from generic_composition.terms import BudgetExceeded, SourceTerm, Term, render, subterms
from .balanced import balanced_tokens

Budget = _v3.Budget
_CONTENT = {'string_content', 'string_fragment', 'interpreted_string_literal_content',
            'raw_string_literal_content'}


def refine_literals(converted, *, max_nodes, statistics=None):
    """Swap the same literal leaves v3 refines, retaining exact UTF-8 spans.

    Unsupported delimiter/quote conventions fall back to the frozen flat-token
    representation. Host-language escape decoding and multi-child content nodes
    are deliberately outside this adapter; their original AST remains intact.
    """
    statistics = Counter() if statistics is None else statistics
    positions = {}

    def convert(node, path):
        position = converted.spans[path]
        positions[path] = position
        if not node.children and node.kind in _CONTENT and isinstance(node.atom, str):
            try:
                view = balanced_tokens(node.atom, source_path=converted.source_path,
                                       start_byte=position.start_byte, max_nodes=max_nodes)
                statistics['balanced_literal_leaves'] += 1
                statistics['balanced_groups'] += sum(
                    n.kind.startswith('balanced_group_') for _, n in subterms(view.term, max_nodes=max_nodes))
            except BudgetExceeded:
                raise
            except ValueError as exc:
                view = flat_strings(SourceTerm(node, {(): position}, converted.source_path, node.atom))
                statistics['flat_fallback_literal_leaves'] += 1
                statistics['fallback:' + str(exc).split(':', 1)[0]] += 1
            for nested, span in view.spans.items():
                positions[path + nested] = span
            if render(view.term) != node.atom:
                raise AssertionError('Literal representation changed source bytes')
            return Term(node.kind, view.term.atom, view.term.children)
        return Term(node.kind, node.atom, tuple(convert(c, path + (i,)) for i, c in enumerate(node.children)))

    result = SourceTerm(convert(converted.term, ()), positions,
                        converted.source_path, converted.original_text)
    list(subterms(result.term, max_nodes=max_nodes))
    if render(result.term) != render(converted.term):
        raise AssertionError('Body representation changed source bytes')
    return result


def balanced_refine(record, max_nodes, *, statistics=None):
    refined = refine_literals(record['tree'], max_nodes=max_nodes, statistics=statistics)
    previous, roles = record['literal_roles'], {}
    for path, _ in subterms(refined.term, max_nodes=max_nodes):
        origin = path
        while origin and origin not in previous:
            origin = origin[:-1]
        if origin in previous:
            roles[path] = previous[origin]
    return dict(record, tree=refined, literal_roles=roles, skeleton=_v3._skeleton(refined.term))


def generate(corpus, budget=Budget()):
    statistics = Counter()

    def refine(record, max_nodes):
        return balanced_refine(record, max_nodes, statistics=statistics)

    result = _v3.generate(corpus, budget, refine=refine)
    result['algorithm'] = 'test_edit_analogy_v4_balanced_literals'
    result['representation'] = {'mode': 'balanced_delimiter_groups_with_flat_fallback',
                                'counts': dict(statistics), 'counting_scope': 'attempted_refinements',
                                'unproved': ['embedded_syntax', 'embedded_bindings', 'embedded_effects', 'oracle_validity']}
    return result


def gate_evidence(corpus, generated, issue):
    evidence, candidates = _v3.gate_evidence(corpus, generated, issue)
    evidence['literal_representation_policy'] = (
        'Balanced parentheses, brackets and braces expose literal syntax subtrees. '
        'Unsupported quote/delimiter conventions retain flat tokens. '
        'Grouping does not establish an embedded grammar, binding, effect or oracle contract.')
    return evidence, candidates
