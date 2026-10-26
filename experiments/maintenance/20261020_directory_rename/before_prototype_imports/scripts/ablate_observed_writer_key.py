"""Offline ablation: omit only writer from the existing observed-read key."""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from experimental.observed_write_frontier import fingerprint, project
from relation_search.checkpoint import digest, read, write
from scripts.replay_observed_write_frontier import replay_case


def replay_rows(rows, *, with_writer):
    states, decisions, per_q = {}, [], {}
    counts = Counter()
    baseline = set()
    for row in rows:
        projection = project(row['event'])
        # Qualification stays identical: an unknown writer does not become a
        # valid value-only observation merely because this arm omits its key.
        if projection is None:
            decisions.append(dict(status='unknown_or_unmapped', key=None, new=False,
                                  retained=False, representative=None))
            counts[row['role'] + '_unknown_or_unmapped'] += 1
            continue
        if not with_writer:
            projection.pop('source_writer')
        key = fingerprint(projection)
        owner = row.get('owner')
        representative = (owner['representative'] if owner else
            'unbound_event:' + row['trace'] + '#' + str(row['trace_line']))
        new = key not in states
        states.setdefault(key, dict(projection=projection, representative=representative))
        decisions.append(dict(status='observed', key=key, new=new, retained=new,
                              representative=representative))
        counts[row['role'] + '_observed'] += 1
        counts[row['role'] + '_new_states'] += new
        if row['role'] == 'control':
            baseline.add(key)
        q_key = fingerprint(projection['source_q'])
        q = per_q.setdefault(q_key, dict(source_q=projection['source_q'],
                                         control_keys=set(), keys=set(), generated_keys=set()))
        q['keys'].add(key)
        if row['role'] == 'control':
            q['control_keys'].add(key)
        elif new:
            q['generated_keys'].add(key)
    candidates = sorted({decision['representative'] for row, decision in zip(rows, decisions)
        if row['role'] == 'generated' and row.get('owner') and decision['retained']})
    q_counts = {key: dict(source_q=value['source_q'], control_states=len(value['control_keys']),
        states=len(value['keys']), generated_new_states=len(value['generated_keys']))
        for key, value in sorted(per_q.items())}
    summary = dict(counters=dict(counts), control_state_count=len(baseline),
        state_count=len(states), retained_generated_candidates=len(candidates),
        generated_representatives=candidates, per_source_q=q_counts)
    return dict(summary=summary, decisions=decisions, states=states)


def verify_seal(folder):
    seal = read(folder / 'seal.json')
    for relative, checksum in seal['files_sha256'].items():
        if digest(folder / relative) != checksum:
            raise ValueError('Frozen input changed: ' + str(folder / relative))
    return len(seal['files_sha256'])


def run(execution, reference, output):
    verified_execution = verify_seal(execution)
    verified_reference = verify_seal(reference)
    execution_protocol = read(execution / 'protocol.json')
    original_protocol = read(reference / 'protocol.json')
    if (original_protocol['representative_limit'] != 1
            or original_protocol['input_seal_sha256'] != digest(execution / 'seal.json')):
        raise ValueError('Reference replay is not the requested execution/representative policy')
    output.mkdir(parents=True, exist_ok=False)
    code = [Path(__file__), ROOT / 'scripts/replay_observed_write_frontier.py',
            ROOT / 'experimental/observed_write_frontier.py']
    protocol = dict(input_execution=str(execution.resolve()), input_reference=str(reference.resolve()),
        execution_seal_sha256=digest(execution / 'seal.json'),
        reference_seal_sha256=digest(reference / 'seal.json'),
        verified_execution_files=verified_execution, verified_reference_files=verified_reference,
        groups=[dict(case=r['case'], group=r['group']) for r in execution_protocol['selected']],
        order='separate case frontiers; all controls first, then generated groups and JSONL events in frozen execution order',
        qualification='unchanged project(event); unknown/unmapped remains excluded in both arms',
        intervention='only omit source_writer from the projected key; retain source q, allocation, binding and exact scalar',
        representatives_per_state=1, target_or_verdict_selection=False,
        mode='offline evidence replay, not online search or search-benefit evaluation',
        provider_calls=0, docker_calls=0,
        code_sha256={str(p.relative_to(ROOT)): digest(p) for p in code})
    # Freeze the intervention and complete input list before deriving outcomes.
    write(output / 'protocol.json', protocol)
    for path in code:
        destination = output / 'code_snapshot' / path.relative_to(ROOT)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(path.read_bytes())

    comparisons = []
    for case in sorted({r['case'] for r in execution_protocol['selected']}):
        selected = [r for r in execution_protocol['selected'] if r['case'] == case]
        _, rows, retained, snapshot = replay_case(case, selected, 1)
        if (rows != read(reference / case / 'observations.json')
                or retained != read(reference / case / 'retained.json')
                or snapshot != read(reference / case / 'frontier.json')):
            raise ValueError('Raw replay differs from the sealed original frontier')
        writer = replay_rows(rows, with_writer=True)
        value = replay_rows(rows, with_writer=False)
        for original, decision in zip(rows, writer['decisions']):
            if any(original['result'][key] != decision[key]
                   for key in ('status', 'key', 'new', 'retained')):
                raise ValueError('Ablation implementation changed the reference arm')
        with_candidates = set(writer['summary']['generated_representatives'])
        without_candidates = set(value['summary']['generated_representatives'])
        changed = [dict(trace=row['trace'], trace_line=row['trace_line'], role=row['role'],
                        group=row['group'], with_writer=a, without_writer=b)
                   for row, a, b in zip(rows, writer['decisions'], value['decisions'])
                   if a['retained'] != b['retained']]
        comparison = dict(case=case, groups=len(selected), raw_replay_matches_reference=True,
            with_writer=writer['summary'], without_writer=value['summary'],
            retained_only_with_writer=sorted(with_candidates - without_candidates),
            retained_only_without_writer=sorted(without_candidates - with_candidates),
            changed_retention_events=changed,
            same_representatives=with_candidates == without_candidates,
            same_per_source_q_counts=writer['summary']['per_source_q'] == value['summary']['per_source_q'])
        comparisons.append(comparison)
        write(output / case / 'with_writer.json', writer)
        write(output / case / 'without_writer.json', value)
    write(output / 'summary.json', comparisons)
    write(output / 'seal.json', dict(files_sha256={str(p.relative_to(output)): digest(p)
        for p in sorted(output.rglob('*')) if p.is_file()}))
    return comparisons


if __name__ == '__main__':
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('--execution', required=True, type=Path)
    parser.add_argument('--reference', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    results = run(args.execution, args.reference, args.output)
    print(json.dumps([{key: result[key] for key in
        ('case', 'same_representatives', 'same_per_source_q_counts', 'retained_only_with_writer',
         'retained_only_without_writer')} for result in results], sort_keys=True))
