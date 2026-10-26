"""v5 composition with only the two neighbor orders changed.

Requires the optional ``neighbor_order`` callback in the shared v3 driver.
The existing C truncation, B shape-diversity schedule, focus round-robin,
composition views, validation, gate and budgets remain unchanged.
"""
from prototypes.statement_aligned_test_analogy_v03.generate import Budget, generate as _generate
from prototypes.unified_view_test_analogy_v05.generate import gate_evidence
from prototypes.unified_view_test_analogy_v05.views import compose_views
from .core import rank_neighbors


def generate(corpus, budget=Budget()):
    cache = {}

    def order(A, neighbors, *, capsules, phase):
        return rank_neighbors(A, neighbors, capsules=capsules, phase=phase, cache=cache)

    result = _generate(corpus, budget, compose_views=compose_views, neighbor_order=order)
    result['algorithm'] = 'test_edit_analogy_v5_observation_priority'
    result['counts']['attempted_views'] = result['counts'].pop('attempted_orders')
    result['neighbor_ordering'] = 'actual_observer_and_change_dependence_v1'
    for candidate in result['candidates']:
        candidate['kind'] = 'multiview_test_edit_analogy'
        candidate['composition_view'] = candidate['provenance']['view']
    for rule in result['rules']:
        rule['kind'] = 'multiview_test_edit_analogy'
    return result
