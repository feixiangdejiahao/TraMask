"""Allocate a bounded admission frontier without evaluation-label selection.

Inputs are already executed failing search hypotheses. Selection reuses the
existing source-shape round-robin policy; runtime messages, model answers and
evaluation labels do not rank candidates. Unselected candidates remain pending,
not valid, invalid, or independent evidence that no gap exists.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
import importlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from relation_search.admission import program_candidate
from relation_search import semantic_selection
from scripts.evaluate_test_validity import digest, loaded_local_sources, read, verify_seal, write_new


VERSION = 'source-shape-failing-admission-frontier.v1'


def prepare(input_path, output, *, per_case=16):
    if type(per_case) is not int or per_case < 0:
        raise ValueError('per-case query budget must be a nonnegative integer')
    inventory = read(input_path)
    # This is the only inventory section consumed by the selector. The public
    # task key groups inputs, but never enters semantic ranking or provider data.
    records = inventory['controlled_failures']
    importlib.import_module('relational_gap.balanced_reachability')
    algorithm = loaded_local_sources()
    cache, by_case = {}, defaultdict(list)
    for record in records:
        by_case[record['case']].append(record)
    output.mkdir(parents=True, exist_ok=False)
    selected, cases = [], []
    for case, rows in sorted(by_case.items()):
        identities = {(row['inputs']['corpus']['sha256'], row['inputs']['frontend']['sha256']) for row in rows}
        if len(identities) != 1:
            raise ValueError('One frontier task must refer to one frozen source snapshot')
        candidates, occurrences, corpus = {}, {}, None
        for row in rows:
            paths = tuple(row['inputs'][name]['path'] for name in ('corpus', 'frontend', 'candidates'))
            if paths not in cache:
                for name in ('corpus', 'frontend', 'candidates'):
                    receipt = row['inputs'][name]
                    if digest(receipt['path']) != receipt['sha256']:
                        raise ValueError('Frozen source receipt changed')
                cache[paths] = (read(paths[0]), {c['id']: c for c in read(paths[2])})
            source, accepted = cache[paths]
            corpus = source
            candidate = program_candidate(accepted[row['candidate_id']])
            identifier = candidate['id']
            if identifier in candidates and semantic_selection._material(candidates[identifier]) != semantic_selection._material(candidate):
                raise ValueError('One candidate identity has different program content')
            candidates[identifier] = candidate
            # Baseline chronological order preserves one execution receipt per
            # candidate. No failure text or pass/fail details enter the selector.
            occurrences.setdefault(identifier, row)
        allocation = semantic_selection.select(corpus, list(candidates.values()), budget=per_case)
        selected.extend(occurrences[candidate['id']] for candidate in allocation['selected'])
        cases.append(dict(case=case, candidates=len(candidates), selected=allocation['selected_count'],
                          ranking=allocation['ranking'], policy_sha256=allocation['policy_sha256']))
        print(json.dumps(dict(case=case, candidates=len(candidates), selected=allocation['selected_count'])), flush=True)
    verify_seal(algorithm)
    newly_loaded = set(loaded_local_sources()) - set(algorithm)
    if newly_loaded:
        raise ValueError('Unsealed source imported during selection')
    pending = len(records) - len(selected)
    write_new(output/'selected_inventory.json', dict(version=VERSION, controlled_failures=selected,
        source_inventory=dict(path=str(input_path.resolve()), sha256=digest(input_path)),
        source_only_ranking=True, selected_without_positive_or_review_labels=True,
        unselected_status='pending_admission_budget', unselected_occurrences=pending))
    manifest = dict(version=VERSION, source_inventory=dict(path=str(input_path.resolve()), sha256=digest(input_path)),
        algorithm=algorithm, selection_policy=semantic_selection.POLICY, per_case=per_case, cases=cases,
        input_occurrences=len(records), selected_occurrences=len(selected), pending_occurrences=pending,
        selected_inventory=dict(path=str((output/'selected_inventory.json').resolve()), sha256=digest(output/'selected_inventory.json')),
        provider_calls=0, native_executions_reused=True, evaluation_labels_used=False,
        runtime_outcomes_used_only_for_initial_failing_pool=True,
        runtime_messages_used_for_ranking=False,
        interpretation='Bounded source-only frontier; selection is neither test validity nor gap detection.')
    write_new(output/'manifest.json', manifest)
    return dict(selected_occurrences=len(selected), pending_occurrences=pending, tasks=len(cases), provider_calls=0)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--per-case', type=int, default=16)
    args = parser.parse_args()
    print(json.dumps(prepare(args.input, args.output, per_case=args.per_case)))
