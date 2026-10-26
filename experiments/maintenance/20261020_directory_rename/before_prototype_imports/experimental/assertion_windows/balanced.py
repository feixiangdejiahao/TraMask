"""Window generator with only the existing balanced literal view substituted."""
from collections import Counter

from experimental.generic_v4.generate import balanced_refine
from .generate import Budget, generate as _generate, gate_evidence as _evidence


def generate(corpus, budget=Budget()):
    statistics = Counter()

    def refine(record, max_nodes):
        return balanced_refine(record, max_nodes, statistics=statistics)

    result = _generate(corpus, budget, refine=refine)
    result['algorithm'] = 'test_edit_analogy_contiguous_windows_balanced_literals'
    result['representation'] = {
        'mode': 'balanced_delimiter_groups_with_flat_fallback',
        'counts': dict(statistics),
        'unproved': ['embedded_syntax', 'embedded_bindings', 'embedded_effects', 'oracle_validity'],
    }
    return result


def gate_evidence(corpus, generated, issue):
    evidence, candidates = _evidence(corpus, generated, issue)
    evidence['literal_representation_policy'] = (
        'Parentheses, brackets and braces in supported string leaves are grouped '
        'without changing source bytes. Unsupported forms retain flat tokens. '
        'This does not prove an embedded grammar, binding, effect or oracle contract.')
    return evidence, candidates
