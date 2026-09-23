"""v3 search/validation driver with a unified raw/aligned composition callback."""
from experimental.generic_v3.generate import Budget, generate as _generate
from experimental.generic_v3.generate import gate_evidence as _evidence
from .views import compose_views


def generate(corpus, budget=Budget()):
    result = _generate(corpus, budget, compose_views=compose_views)
    result['algorithm'] = 'test_edit_analogy_v5_raw_and_observer_aligned_views'
    result['counts']['attempted_views'] = result['counts'].pop('attempted_orders')
    for candidate in result['candidates']:
        candidate['kind'] = 'multiview_test_edit_analogy'
        candidate['composition_view'] = candidate['provenance']['view']
    for rule in result['rules']:
        rule['kind'] = 'multiview_test_edit_analogy'
    return result


def gate_evidence(corpus, generated, issue):
    evidence, candidates = _evidence(corpus, generated, issue)
    evidence['composition_policy'] = (
        'Each triple was tried as raw syntax and, when possible, as aligned direct statements. '
        'Raw views may delete source operations or erase source parameters; this is a hypothesis, not proof. '
        'Aligned views prefer actual-observer call/field labels and fall back to structural anchors. '
        'Only aligned views claim exact unmatched C statement retention in the displayed order. '
        'All views require semantic admission of bindings, effects and the transported oracle.')
    return evidence, candidates
