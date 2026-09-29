"""Finite search bookkeeping over actual probe events.

Source hypotheses and executed profiles are deliberately separate. A requested
shape is never counted as reached merely because its AST edit was emitted.
"""
from __future__ import annotations

from collections import defaultdict, deque
import hashlib
import json


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), default=str).encode()).hexdigest()


def _observed_roles(event):
    roles = event.get('roles', {})
    if isinstance(roles, list):
        roles = {row['name']: row['value'] for row in roles
                 if row.get('status') == 'observed' and 'value' in row}
    return {name: value for name, value in roles.items()
            if not (isinstance(value, dict) and value.get('status') == 'unknown')}


def _snapshot_values(roles):
    """Resolve encoded references only within this actual snapshot.

    A repeated container omits its items in the logger representation; that
    omission is not an empty container. Nested containers can be the first
    complete occurrence of an alias, so index them before projecting roles.
    """
    values, pending = {}, list(roles.values())
    while pending:
        value = pending.pop()
        if isinstance(value, list):
            pending.extend(value)
        elif isinstance(value, dict) and 'type' in value:
            if 'alias' in value and not value.get('reference'):
                values[value['alias']] = value
            pending.extend(value.get('items', []))
    return values


def canonical_profile(event):
    """Keep source roles/cuts, alias partitions and joint relative values.

    Concrete addresses are never accepted as a cross-run identity. Unknown
    probes remain unknown, rather than manufacturing an uncovered atom.
    """
    roles = event.get('roles', {})
    origins = event.get('role_origins')
    if isinstance(roles, list):
        origins = [(row['name'], row.get('origin_span'), row.get('kind', 'read')) for row in roles]
    roles = _observed_roles(event)
    snapshot = _snapshot_values(roles)
    numbers, presence, kinds, strings = [], [], [], []
    for name, value in sorted(roles.items()):
        truncated = False
        if isinstance(value, dict) and 'type' in value:
            if value.get('reference'):
                value = snapshot.get(value.get('alias'))
                if value is None:
                    # Unresolved content is unknown; retain any separately
                    # measured alias partition, never manufacture absence.
                    continue
            tag = value['type']
            if tag == 'dict':
                # Actual input keys, not serialization metadata keys. Truncated
                # dictionaries remain partial observations and cannot prove
                # absence outside the captured prefix.
                keys = [item[0].get('value') for item in value.get('items', [])
                        if item[0].get('type') in ('str', 'int', 'bool', 'NoneType')]
                presence.append((name, sorted(keys, key=repr), bool(value.get('truncated'))))
                continue
            if tag in ('list', 'tuple'):
                presence.append((name, value.get('length'), bool(value.get('truncated'))))
                continue
            if tag == 'bytes':
                raw = bytes.fromhex(value.get('hex', ''))
                strings.append((name, bool(raw), any(chr(c).isspace() for c in raw),
                                39 in raw, 34 in raw, bool(value.get('truncated'))))
                continue
            if 'value' not in value:
                kinds.append((name, tag, 'opaque'))
                continue
            truncated = bool(value.get('truncated'))
            value = value['value']
        if type(value) in (int, float):
            numbers.append((name, value))
        elif isinstance(value, dict):
            presence.append((name, sorted(str(k) for k in value)))
        elif isinstance(value, (list, tuple)):
            presence.append((name, len(value)))
        elif isinstance(value, str):
            strings.append((name, bool(value), any(c.isspace() for c in value), "'" in value, '"' in value,
                            truncated))
        elif value is None or isinstance(value, bool):
            kinds.append((name, value))
    order = [(left, right, (a > b) - (a < b))
             for i, (left, a) in enumerate(numbers) for right, b in numbers[i+1:]]
    return dict(window=event.get('source_window'), phase=event.get('phase'),
                provenance=origins, order=order,
                presence=presence, scalar=kinds, strings=strings,
                aliases=event.get('alias_partition', []))


class Frontier:
    def __init__(self, representatives=2):
        self.representatives = representatives
        self.profiles = defaultdict(list)

    def snapshot(self):
        state = dict(version=1, representatives=self.representatives,
                     profiles=dict(sorted(self.profiles.items())))
        return {**state, 'sha256': fingerprint(state)}

    @classmethod
    def restore(cls, snapshot):
        state = {key: value for key, value in snapshot.items() if key != 'sha256'}
        if state.get('version') != 1 or snapshot.get('sha256') != fingerprint(state):
            raise ValueError('Frontier checkpoint changed or unsupported')
        result = cls(state['representatives'])
        for key, members in state['profiles'].items():
            if len(members) > result.representatives or len(members) != len(set(members)):
                raise ValueError('Invalid Frontier representative set')
            result.profiles[key] = list(members)
        return result

    def observe(self, candidate_id, events):
        new, retained, keys = [], False, []
        for event in events:
            if not _observed_roles(event):
                continue
            profile = canonical_profile(event)
            key = fingerprint(profile)
            keys.append(key)
            members = self.profiles[key]
            if not members:
                new.append(profile)
            if candidate_id not in members and len(members) < self.representatives:
                members.append(candidate_id)
                retained = True
        return dict(candidate_id=candidate_id, measured_profiles=keys,
                    new_profiles=new, retained=retained,
                    status='runtime_observed' if keys else 'no_runtime_profile')


def select_round(candidates, budget=128, previously_executed=()):
    """Give the least-served operator its next source-ordered proposal.

    Service counts persist through attempted physical edits across rounds.
    Source order within each operator remains stable; metadata-only aliases
    cannot consume another attempt.
    """
    from experimental.candidate_scheduling import select
    return select(candidates, budget, previously_executed)
