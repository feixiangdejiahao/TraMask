"""Bound source call expansion across seeds, before spending on deeper paths.

Scheduling is breadth first globally, with resolved paths before hypotheses at
each depth and one pending edge per seed per turn. Unknown edges remain eligible
when their turn fits the budget. Changed roots are mandatory and do not consume
the additional-unit budget. This is source reachability, never runtime coverage.
"""
from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class ReachabilityBudget:
    max_units: int = 256
    max_depth: int = 3
    max_edges: int = 65536
    max_reasons_per_function: int = 64
    max_reported_omissions: int = 128

    def __post_init__(self):
        for key, value in asdict(self).items():
            if type(value) is not int or value < (0 if key in {'max_units', 'max_depth'} else 1):
                raise ValueError('reachability bounds must be nonnegative; work/report bounds positive')


def _edge_key(edge):
    span = edge.get('call_span') or {}
    return (span.get('path', ''), span.get('start_byte', -1), span.get('end_byte', -1),
            edge['callee_id'], edge.get('reason', ''))


def balanced_reachability(seed_ids, expand, *, changed_roots=(), budget=None, eligible=None):
    """Return compact reasons and admitted function IDs from source call edges.

    ``expand(function_id)`` returns records with ``callee_id``, ``resolved`` and
    optional source ``call_span``/``reason``. It is cached once per function.
    ``eligible`` excludes non-production owners such as registered tests. Input
    seed order is stable caller priority, not Python set iteration order.
    """
    budget = budget or ReachabilityBudget()
    seeds = list(dict.fromkeys(seed_ids))
    mandatory = set(changed_roots)
    chosen, reached, reasons = set(), set(), defaultdict(list)
    for function_id in sorted(mandatory):
        reasons[function_id].append({'kind': 'changed_function', 'test_id': None, 'depth': 0})
    adjacency, processed, omitted, omitted_ids = {}, 0, 0, set()
    seen = {seed: {(seed, True)} for seed in seeds}
    frontier = {seed: [(seed, (), True)] for seed in seeds}
    exhausted_edges = False
    truncated_reasons = 0

    def edges(function_id):
        if function_id not in adjacency:
            unique = {}
            for raw in expand(function_id):
                edge = dict(raw, caller_id=function_id, resolved=raw.get('resolved') is True)
                unique.setdefault((_edge_key(edge), edge['resolved']), edge)
            adjacency[function_id] = sorted(unique.values(), key=lambda edge: (not edge['resolved'], _edge_key(edge)))
        return adjacency[function_id]

    for depth in range(1, budget.max_depth + 1):
        queues = {True: {}, False: {}}
        for seed in seeds:
            for function_id, path, proved in frontier.get(seed, ()):
                for edge in edges(function_id):
                    target = edge['callee_id']
                    if target == seed or eligible is not None and not eligible(target):
                        continue
                    status = proved and edge['resolved']
                    queues[status].setdefault(seed, deque()).append((target, (*path, edge), status))
        following = defaultdict(list)
        for status in (True, False):
            rotation = deque(seed for seed in seeds if seed in queues[status])
            while rotation:
                if processed >= budget.max_edges:
                    exhausted_edges = True
                    break
                seed = rotation.popleft()
                target, path, proved = queues[status][seed].popleft()
                if queues[status][seed]:
                    rotation.append(seed)
                processed += 1
                state = target, proved
                if state in seen[seed]:
                    continue
                seen[seed].add(state)
                if target not in mandatory and target not in chosen:
                    if len(chosen) >= budget.max_units:
                        omitted += 1
                        if len(omitted_ids) < budget.max_reported_omissions:
                            omitted_ids.add(target)
                        continue
                    chosen.add(target)
                reached.add(target)
                if len(reasons[target]) < budget.max_reasons_per_function:
                    reasons[target].append({'kind': 'test_call_reachability', 'test_id': seed,
                                            'depth': depth, 'path': list(path), 'resolved': proved})
                else:
                    truncated_reasons += 1
                following[seed].append((target, path, proved))
            if exhausted_edges:
                break
        frontier = following
        if exhausted_edges or not frontier:
            break
    return {'function_ids': sorted(mandatory | chosen), 'reached_function_ids': sorted(reached),
            'reasons': dict(reasons), 'budget': asdict(budget),
            'stats': {'seeds': len(seeds), 'mandatory_units': len(mandatory), 'additional_units': len(chosen),
                      'expanded_units': len(adjacency), 'processed_edges': processed,
                      'unit_budget_reached': len(chosen) >= budget.max_units,
                      'edge_budget_exhausted': exhausted_edges, 'omitted_path_count': omitted,
                      'omitted_function_ids': sorted(omitted_ids), 'truncated_reason_count': truncated_reasons},
            'status': 'source_reachability_only_unknown_edges_retained_within_budget'}


def frontend_reachability(index, tests, *, max_depth=3, max_units=256):
    """Small deferred integration adapter; does not mutate frontend records."""
    from anchor_retrieval.syntax import CALLS
    from .frontend import _flow_for_test, _owned_walk, _resolved_targets, _test_walk, TRUSTED_RESOLUTIONS

    def expand(function_id):
        unit = index.units[function_id]
        nodes = list(_test_walk(unit.body) if unit.test else _owned_walk(unit.body))
        flow = _flow_for_test(index, unit, nodes) if unit.test else index.flow(function_id)
        calls = {(flow.nodes[call.node]['start_byte'], flow.nodes[call.node]['end_byte']): call for call in flow.calls}
        targets = {position: call.targets for position, call in calls.items()}
        for node in nodes:
            if node.type in CALLS:
                position = node.start_byte, node.end_byte
                targets[position] = _resolved_targets(index, unit, node, calls.get(position))
        for (start, end), options in sorted(targets.items()):
            for target, reason in options:
                yield {'callee_id': target, 'reason': reason, 'resolved': reason in TRUSTED_RESOLUTIONS,
                       'call_span': {'path': unit.source.path, 'start_byte': start, 'end_byte': end}}

    return balanced_reachability([unit.id for unit in tests], expand, changed_roots=index.changed,
                                 budget=ReachabilityBudget(max_units=max_units, max_depth=max_depth),
                                 eligible=lambda target: target in index.units and not index.units[target].test)
