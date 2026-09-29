"""Exact edited-input identity, independent of generator bookkeeping.

This is textual identity under the same source test, not behavioral equivalence.
Runtime probes remain evidence attached to a proposal rather than input edits.
"""
import hashlib
import json


def input_identity(candidate):
    edits = []
    for row in candidate.get('edits', []):
        if row.get('role') == 'relation_runtime_probe':
            continue
        span = row['span']
        edits.append((span['path'], span['start_byte'], span['end_byte'], row['before'], row['after']))
    imports = sorted(json.dumps(row, sort_keys=True, separators=(',', ':'))
                     for row in candidate.get('imports', []))
    material = [candidate['base_test_id'], sorted(edits), imports]
    return hashlib.sha256(json.dumps(material, separators=(',', ':')).encode()).hexdigest()


def distinct_inputs(candidates, previous_ids=()):
    previous = set(previous_ids)
    seen = {input_identity(row) for row in candidates if row['id'] in previous}
    kept, duplicates = [], []
    for row in candidates:
        key = input_identity(row)
        if key in seen:
            duplicates.append({'id': row['id'], 'input_identity': key})
            continue
        seen.add(key)
        kept.append(row)
    return kept, duplicates
