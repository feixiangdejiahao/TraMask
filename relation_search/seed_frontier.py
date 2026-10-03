"""Serve relevant source tests before candidate operator families.

Each source test gets one candidate before its second candidate. Existing
within-test order is preserved. Source retrieval rank orders the source tests.
This policy changes opportunity allocation only, never candidate validity.
"""
from __future__ import annotations

from collections import defaultdict
import copy
import hashlib
import json


POLICY = dict(version='retrieval-seed-round-robin.v1',
    grouping='base_test_id, never case or candidate identifiers',
    seed_order='source retrieval rank, then minimum material SHA256',
    within_seed='unchanged prior source ranking',
    rounds='one next candidate from each ordered source test',
    unknown_rank='after all known source retrieval ranks',
    forbidden_inputs=['runtime outcomes','model responses','evaluation labels','target witnesses'])


def rank(rows):
    groups = defaultdict(list)
    for row in rows:
        groups[row['base_test_id']].append(row)
    def order(seed):
        values = groups[seed]
        ranks = [row['source_retrieval_rank'] for row in values
                 if type(row.get('source_retrieval_rank')) is int and row['source_retrieval_rank'] >= 0]
        return (min(ranks, default=10**12), min(row['content_sha256'] for row in values))
    seeds = sorted(groups, key=order)
    result = []
    for position in range(max(map(len, groups.values()), default=0)):
        for seed in seeds:
            if position >= len(groups[seed]):
                continue
            row = copy.deepcopy(groups[seed][position])
            row.update(prior_rank=row['rank'], rank=len(result)+1,
                       seed_service_round=position, selected=False)
            result.append(row)
    return result


def policy_sha():
    return hashlib.sha256(json.dumps(POLICY, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
