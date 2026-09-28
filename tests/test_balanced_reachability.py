"""Independent bounded graph and source-helper scheduling examples."""
import json

import pytest

from relational_gap.balanced_reachability import ReachabilityBudget, balanced_reachability, frontend_reachability


def edge(target, resolved=True, position=0):
    return {'callee_id': target, 'resolved': resolved, 'reason': 'resolved_source' if resolved else 'name_guess',
            'call_span': {'path': 'toy.py', 'start_byte': position, 'end_byte': position + 1}}


def test_direct_entries_of_all_seeds_precede_deep_expansion():
    graph = {'a': [edge('a1')], 'a1': [edge('a2')], 'a2': [edge('a3')], 'b': [edge('helper')]}
    result = balanced_reachability(['a', 'b'], lambda key: graph.get(key, []),
                                  budget=ReachabilityBudget(max_units=2))
    assert result['function_ids'] == ['a1', 'helper']
    assert result['stats']['omitted_function_ids'] == ['a2']


def test_each_depth_is_round_robin_across_seeds_and_resolved_edges_go_first():
    graph = {'a': [edge('guess', False), edge('a1', position=1), edge('a2', position=2)],
             'b': [edge('b1')]}
    result = balanced_reachability(['a', 'b'], lambda key: graph.get(key, []),
                                  budget=ReachabilityBudget(max_units=2))
    assert result['function_ids'] == ['a1', 'b1']
    assert set(result['stats']['omitted_function_ids']) == {'a2', 'guess'}


def test_unknown_edges_remain_eligible_after_resolved_edges_with_explicit_unproved_path():
    graph = {'a': [edge('guess', False)], 'guess': [edge('next')]}
    result = balanced_reachability(['a'], lambda key: graph.get(key, []))
    assert result['function_ids'] == ['guess', 'next']
    assert all(not row['resolved'] for values in result['reasons'].values() for row in values)
    assert result['reasons']['next'][0]['depth'] == 2


def test_changed_roots_survive_zero_extra_budget_and_are_not_double_charged():
    graph = {'test': [edge('changed'), edge('other')]}
    result = balanced_reachability(['test'], lambda key: graph.get(key, []), changed_roots=['changed'],
                                  budget=ReachabilityBudget(max_units=0))
    assert result['function_ids'] == ['changed']
    assert result['stats']['additional_units'] == 0
    assert [row['kind'] for row in result['reasons']['changed']] == ['changed_function', 'test_call_reachability']


def test_shared_descendants_cycles_and_proof_upgrades_are_bounded_and_expand_once():
    graph = {'a': [edge('shared', False), edge('bridge', position=1)], 'b': [edge('shared')],
             'bridge': [edge('shared')], 'shared': [edge('bridge')]}
    called = []
    def expand(key):
        called.append(key)
        return graph.get(key, [])
    result = balanced_reachability(['a', 'b'], expand, budget=ReachabilityBudget(max_depth=8))
    assert len(called) == len(set(called))
    rows = [row for row in result['reasons']['shared'] if row['test_id'] == 'a']
    assert {(row['depth'], row['resolved']) for row in rows} == {(1, False), (2, True)}
    assert result['stats']['processed_edges'] < 20


def test_work_and_provenance_budgets_are_reported():
    graph = {seed: [edge('shared')] for seed in ['a', 'b', 'c']}
    result = balanced_reachability(graph, lambda key: graph.get(key, []),
                                  budget=ReachabilityBudget(max_edges=2, max_reasons_per_function=1))
    assert result['stats']['edge_budget_exhausted']
    assert result['stats']['processed_edges'] == 2
    assert result['stats']['truncated_reason_count'] == 1
    assert len(result['reasons']['shared']) == 1


def test_input_edge_order_does_not_change_result_and_ineligible_owners_are_not_expanded():
    graph = {'a': [edge('z', position=3), edge('skip'), edge('b', position=2)]}
    kwargs = {'eligible': lambda key: key != 'skip'}
    first = balanced_reachability(['a'], lambda key: graph.get(key, []), **kwargs)
    second = balanced_reachability(['a'], lambda key: reversed(graph.get(key, [])), **kwargs)
    assert first == second
    assert first['function_ids'] == ['b', 'z']
    json.dumps(first)


@pytest.mark.parametrize('kwargs', [{'max_units': -1}, {'max_depth': -1}, {'max_edges': 0}, {'max_units': True}])
def test_invalid_budgets_rejected(kwargs):
    with pytest.raises(ValueError):
        ReachabilityBudget(**kwargs)


def test_source_adapter_recovers_late_helper_at_same_budget_as_two_direct_entries():
    from anchor_retrieval.syntax import Source
    from relational_gap.frontend import _FrontendIndex
    sources = [Source('grammar.py', '''import re
class Parser:
    def parse(self, value):
        return re.fullmatch(r'([a-z]+):([0-9]+)', value) is not None
def unrelated(value): return deep(value)
def deep(value): return value
''', 'python'), Source('test_grammar.py', '''from grammar import Parser, unrelated
def test_first_budget_consumer():
    assert unrelated('noise')
def helper(value):
    p = Parser()
    return p.parse(value)
def test_first(): assert helper('red:1')
def test_second(): assert helper('blue:2')
''', 'python')]
    index = _FrontendIndex(sources, '', max_depth=3, max_reachable=2)
    changed = next(unit.id for unit in index.units.values() if unit.name == 'parse')
    index.changed.add(changed)
    tests = sorted((unit for unit in index.units.values() if unit.test), key=lambda unit: unit.node.start_byte)
    result = frontend_reachability(index, tests, max_units=2)
    helper = next(unit.id for unit in index.units.values() if unit.name == 'helper')
    assert helper in result['function_ids']
    assert any(row.get('test_id') == tests[1].id and row['depth'] == 2 and row['resolved']
               for row in result['reasons'][changed])
    from relational_gap.frontend import extract_frontend, to_emitter_corpus
    from relational_gap.regex_cells import generate_regex_cells
    patch = '''diff --git a/grammar.py b/grammar.py
--- a/grammar.py
+++ b/grammar.py
@@ -4 +4 @@
-        return False
+        return re.fullmatch(r'([a-z]+):([0-9]+)', value) is not None
'''
    facts = extract_frontend(sources, patch=patch, max_production_units=2)
    assert any(call['function_id'] == helper for call in facts['production_calls'])
    regex = generate_regex_cells(to_emitter_corpus(facts), facts)
    assert len(regex['candidates']) == 4
