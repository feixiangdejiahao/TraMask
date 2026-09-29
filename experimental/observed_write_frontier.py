"""Deterministic bookkeeping over mapped, observed scalar writes.

This is a replay prototype, not a search policy or oracle. Object tokens join
events inside one execution only and are deliberately absent from the key.
Unknown observations never create a state.

For fixed source snapshots, q, allocation and writer locations form finite
sets. Values use exact scalar equality, however, so the state domain is not
finite in general. Only the set observed under a bounded execution is finite.
No semantic-equivalence or finite-domain result is claimed, and more observed
states alone do not establish more effective search feedback.
"""
from __future__ import annotations

import hashlib
import json
import math


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'),
                      ensure_ascii=True, allow_nan=False)


def fingerprint(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def _site(event, span_name, hash_name):
    span, checksum = event.get(span_name), event.get(hash_name)
    if (type(span) is not dict or type(checksum) is not str or len(checksum) != 64
            or any(c not in '0123456789abcdef' for c in checksum)):
        return None
    if (type(span.get('path')) is not str or not span['path']
            or type(span.get('start_byte')) is not int
            or type(span.get('end_byte')) is not int
            or not 0 <= span['start_byte'] < span['end_byte']):
        return None
    return dict(path=span['path'], start_byte=span['start_byte'],
                end_byte=span['end_byte'], sha256=checksum)


def scalar(encoded):
    """Canonicalize exact builtins only; distinguish bool, int and float."""
    if type(encoded) is not dict or encoded.get('status') != 'observed':
        return None
    tag, value = encoded.get('type'), encoded.get('value')
    if tag == 'bool' and type(value) is bool:
        return dict(type=tag, value=value)
    if tag == 'int' and type(value) is int:
        return dict(type=tag, decimal=str(value))
    if tag == 'float' and type(value) is float and math.isfinite(value):
        return dict(type=tag, hex=value.hex())
    if tag == 'str' and type(value) is str:
        return dict(type=tag, value=value)
    if tag == 'NoneType' and 'value' in encoded and value is None:
        return dict(type=tag, value=None)
    if tag == 'bytes' and type(encoded.get('hex')) is str:
        try:
            return dict(type=tag, hex=bytes.fromhex(encoded['hex']).hex())
        except ValueError:
            return None
    return None


def project(event):
    if (event.get('kind') != 'assertion_read'
            or event.get('status') != 'observed_within_instrumented_code'):
        return None
    q = _site(event, 'source_q_span', 'source_q_sha256')
    allocation = _site(event, 'source_allocation_span', 'source_allocation_sha256')
    writer = _site(event, 'source_last_observed_writer', 'source_last_observed_writer_sha256')
    value = scalar(event.get('value'))
    binding = {key: event.get(key) for key in ['class_id', 'field', 'observed_field']}
    if any(item is None for item in [q, allocation, writer, value]):
        return None
    if any(type(item) is not str or not item for item in binding.values()):
        return None
    return dict(version=1, source_q=q, source_allocation=allocation,
                binding=binding, source_writer=writer, value=value)


class Frontier:
    def __init__(self, representatives=1):
        if type(representatives) is not int or representatives < 1:
            raise ValueError('A positive representative count is required')
        self.representatives = representatives
        self.states = {}

    def observe(self, event, representative):
        projection = project(event)
        if projection is None:
            return dict(status='unknown_or_unmapped', new=False, retained=False, key=None)
        if type(representative) is not str or not representative:
            raise ValueError('A stable representative identity is required')
        key = fingerprint(projection)
        new = key not in self.states
        state = self.states.setdefault(key, dict(projection=projection, representatives=[]))
        retained = (representative not in state['representatives']
                    and len(state['representatives']) < self.representatives)
        if retained:
            state['representatives'].append(representative)
        return dict(status='observed', new=new, retained=retained, key=key)

    def snapshot(self):
        state = dict(version=1, representative_limit=self.representatives,
                     states=dict(sorted(self.states.items())))
        # A detached JSON value cannot mutate the live frontier accidentally.
        return json.loads(canonical(dict(**state, sha256=fingerprint(state))))

    @classmethod
    def restore(cls, snapshot):
        state = {k: v for k, v in snapshot.items() if k != 'sha256'}
        if state.get('version') != 1 or fingerprint(state) != snapshot.get('sha256'):
            raise ValueError('Invalid observed-write frontier snapshot')
        result = cls(state['representative_limit'])
        for key, row in state['states'].items():
            members = row['representatives']
            if (fingerprint(row['projection']) != key or len(members) > result.representatives
                    or any(type(m) is not str or not m for m in members)
                    or len(set(members)) != len(members)):
                raise ValueError('Invalid observed-write state')
            result.states[key] = json.loads(canonical(row))
        return result
