"""Finite observation-relative relational cells and minimal source witnesses.

This module is independent of repositories, issue strings, and model calls.
Coordinates must be supplied by a source analysis, never by target labels.
The same value tuple observed on a different object/phase does not cover a cell.
Recorded assertions are not assumed semantically justified from their success.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, dataclass
import hashlib
from itertools import combinations, product
import json
from typing import Any


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(",", ":"))


def identifier(*parts) -> str:
    return hashlib.sha256(canonical(parts).encode()).hexdigest()[:24]


@dataclass(frozen=True)
class ClosureBudget:
    arity: int = 2
    max_axes: int = 16
    max_values_per_axis: int = 24
    max_cells: int = 8192
    max_witnesses: int = 256


def missing_cells(rows: list[dict], *, budget: ClosureBudget = ClosureBudget()) -> dict:
    """Enumerate unseen finite tuples within an exact observation/carrier group.

    Required row fields: id, observation, carrier, coordinates (mapping).
    Optional candidate_version and assertion_justified determine checked status.
    ``observed`` means only present in the supplied evidence; callers must label
    whether those values were statically recovered or dynamically measured.
    Each proposal identifies a seed and coordinate-value donors. This function
    does not claim those substitutions are feasible or preserve the oracle.
    """
    if budget.arity < 1 or budget.max_axes < 1 or budget.max_values_per_axis < 1:
        raise ValueError("Positive finite relation bounds required")
    grouped = defaultdict(list)
    identifiers = set()
    for row in rows:
        if row['id'] in identifiers:
            raise ValueError("Witness row IDs must be unique")
        identifiers.add(row['id'])
        if not isinstance(row.get('coordinates'), dict):
            raise ValueError("Coordinates must be a finite mapping")
        key = canonical([row['observation'], row['carrier'], row.get('candidate_version')])
        grouped[key].append(row)
    gaps, counts, exhausted = [], defaultdict(int), False
    for group_key, members in sorted(grouped.items()):
        members = sorted(members, key=lambda row: row['id'])
        axes = sorted({axis for row in members for axis in row['coordinates']})[:budget.max_axes]
        domains = {}
        for axis in axes:
            domain = {}
            for row in members:
                if axis in row['coordinates']:
                    value = row['coordinates'][axis]
                    domain.setdefault(canonical(value), {'value': value, 'donor': row['id']})
            domains[axis] = [domain[key] for key in sorted(domain)[:budget.max_values_per_axis]]
        for size in range(1, min(budget.arity, len(axes)) + 1):
            for selected in combinations(axes, size):
                observed = defaultdict(list)
                for row in members:
                    if all(axis in row['coordinates'] for axis in selected):
                        observed[canonical([row['coordinates'][axis] for axis in selected])].append(row)
                for assignment in product(*(domains[axis] for axis in selected)):
                    if counts['cells_enumerated'] >= budget.max_cells:
                        exhausted = True
                        break
                    counts['cells_enumerated'] += 1
                    values = [item['value'] for item in assignment]
                    witnessed = observed.get(canonical(values), [])
                    if witnessed:
                        counts['observed_cells'] += 1
                        if any(row.get('assertion_justified') is True and row.get('executed_on_candidate') is True
                               for row in witnessed):
                            counts['checked_cells'] += 1
                        else:
                            counts['observed_but_check_unknown'] += 1
                        continue
                    counts['unseen_cells'] += 1
                    # A minimal coordinate edit, not minimal source-program edit.
                    def cost(row):
                        mismatches = sum(axis not in row['coordinates'] or canonical(row['coordinates'][axis]) != canonical(value)
                                         for axis, value in zip(selected, values))
                        return mismatches, row['id']
                    seed = min(members, key=cost)
                    edits = [{'axis': axis, 'value': item['value'], 'donor_id': item['donor']}
                             for axis, item in zip(selected, assignment)
                             if axis not in seed['coordinates'] or canonical(seed['coordinates'][axis]) != canonical(item['value'])]
                    gaps.append({'id': identifier(group_key, selected, values), 'observation': seed['observation'],
                                 'carrier': seed['carrier'], 'candidate_version': seed.get('candidate_version'),
                                 'constraints': dict(zip(selected, values)), 'seed_id': seed['id'], 'edits': edits,
                                 'coordinate_edit_distance': len(edits), 'feasibility': 'unknown',
                                 'oracle_status': 'requires_independent_justification'})
                if exhausted:
                    break
            if exhausted:
                break
        if exhausted:
            break
    # Round-robin across observation groups prevents one large domain monopolizing output.
    queues = defaultdict(list)
    for gap in sorted(gaps, key=lambda item: (item['coordinate_edit_distance'], item['id'])):
        queues[canonical([gap['observation'], gap['carrier']])].append(gap)
    result = []
    while queues and len(result) < budget.max_witnesses:
        for key in sorted(list(queues)):
            result.append(queues[key].pop(0))
            if not queues[key]:
                del queues[key]
            if len(result) >= budget.max_witnesses:
                break
    return {'gaps': result, 'counts': dict(counts), 'budget': asdict(budget),
            'enumeration_exhausted': exhausted, 'witness_budget_exhausted': len(gaps) > len(result),
            'coverage_status': 'relative_to_supplied_coordinates_and_evidence_only'}


def scalar_relation(left: Any, right: Any) -> str | None:
    """Exact finite scalar relation; bool is not silently treated as an int."""
    if type(left) not in {int, float} or type(right) not in {int, float}:
        return None
    if left != left or right != right:  # NaN has no trichotomy.
        return None
    return 'lt' if left < right else 'gt' if left > right else 'eq'


def interval_relation(a: tuple[int, int], b: tuple[int, int]) -> str:
    """Half-open nonempty intervals; callers must establish interval semantics."""
    sa, ea = a
    sb, eb = b
    if not sa < ea or not sb < eb:
        raise ValueError("Only nonempty intervals are supported")
    if ea <= sb or eb <= sa:
        return 'disjoint'
    if sa == sb and ea == eb:
        return 'equal'
    if sa <= sb and eb <= ea:
        return 'contains'
    if sb <= sa and ea <= eb:
        return 'contained_by'
    return 'partial_overlap'
