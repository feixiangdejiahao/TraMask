"""Ablate only the non-erasing restriction, retaining the v2 search budget."""
from prototypes.test_edit_analogy_v02.generate import Budget, gate_evidence
from prototypes.test_edit_analogy_v02.generate import generate as _generate
from .analogy import analogy


def generate(corpus, budget=Budget()):
    result = _generate(corpus, budget, compose=analogy)
    result['algorithm'] = 'test_edit_analogy_v2_1_allow_erasing_rhs'
    return result
