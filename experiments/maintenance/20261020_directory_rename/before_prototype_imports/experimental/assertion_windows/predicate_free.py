"""Scope-only grouping ablation; same windows, ABC kernel and search budget.

This expands eligible source pairings, not the semantic validity claim. Fixed
budgets can crowd out other proposals, so output counts need not be monotone.
"""
from experimental.assertion_windows import generate as _windows
from experimental.assertion_windows.extract import extract
from experimental.generic_v2.generate import Budget, _refine


def predicate_free_extract(*args, **kwargs):
    result = extract(*args, **kwargs)
    result['instances'] = [dict(record, group_key=record['group_key'][:-1])
                           for record in result['instances']]
    return result


def generate(corpus, budget=Budget(), *, refine=_refine):
    result = _windows.generate(corpus, budget, refine=refine, extractor=predicate_free_extract)
    result.update(algorithm='test_edit_analogy_assertion_windows_predicate_free',
                  grouping_policy='same_lexical_scope_and_parameter_interface; predicate_operator_not_required_equal',
                  grouping_limit='Expanded pairing space is not proof of validity or improved precision; fixed budgets are unchanged.')
    return result


def gate_evidence(corpus, generated, issue):
    evidence, candidates = _windows.gate_evidence(corpus, generated, issue)
    evidence['grouping_policy'] = ('Observation predicates need not match between source windows. '
        'A stronger observation may be transported, but source reconstruction does not establish its oracle. '
        'Judge the complete edited parent under the same semantic admission requirements.')
    return evidence, candidates
