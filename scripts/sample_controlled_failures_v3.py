"""Freeze an outcome-blind ID sample within already controlled native failures.

Eligibility and sampling are preregistered in the evaluator's protocol.json.
No candidate generation, provider calls, repository execution, or target labels.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path

from audit_requested_source_controls import inspect_controls, native
from evaluate_relational_gap import matches_runtime


def read(path):
    return json.loads(Path(path).read_text())


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def named_outcomes(rows):
    evidence = []
    for row in rows:
        tests, errors, _ = native(row['result'])
        names = row['test_ids']
        chosen = [t for t in tests if any(matches_runtime(t['id'], name) for name in names)]
        if errors or not names or any(not any(matches_runtime(t['id'], name) for t in chosen) for name in names):
            return None
        if any(t['status'] not in {'pass', 'fail'} for t in chosen):
            return None
        evidence.append(dict(result=row['result'], result_sha256=sha(row['result']),
                             manifest=row['manifest'], manifest_sha256=sha(row['manifest']),
                             tests=chosen))
    return evidence


def sample(output):
    protocol = read(output / 'protocol.json')
    campaign = Path(protocol['campaign'])
    completed = read(campaign / 'campaign.json')
    population = {}
    for case in protocol['cases']:
        current = next((r for r in completed if r['case'] == case), None)
        round_record = next((r for r in current['rounds'] if r['round'] == 0), None) if current else None
        if round_record is None:
            continue
        runs_path = Path(round_record['runs_index'])
        destination = output / case / 'sample.json'
        if destination.exists():
            old = read(destination)
            assert old['runs_sha256'] == sha(runs_path)
            population[case] = old['eligible_count']
            continue
        runs = read(runs_path)
        grouped = defaultdict(list)
        for row in runs:
            if row['role'] == 'generated':
                grouped[row['candidate_id']].append(row)
        eligible = []
        for cid, rows in grouped.items():
            native_evidence = named_outcomes(rows)
            if native_evidence is None or not any(t['status'] == 'fail' for e in native_evidence for t in e['tests']):
                continue
            control = inspect_controls(rows, runs)
            if control['status'] != 'all_source_controls_passed':
                continue
            eligible.append(dict(candidate_id=cid, native_evidence=native_evidence,
                                 controls=control['controls'], generated_rows=rows))
        eligible.sort(key=lambda row: hashlib.sha256(row['candidate_id'].encode()).hexdigest())
        record = dict(case=case, round=0, protocol_sha256=sha(output / 'protocol.json'),
                      sampler_sha256=sha(__file__), runs_path=str(runs_path), runs_sha256=sha(runs_path),
                      eligible_count=len(eligible), eligible_ids=[r['candidate_id'] for r in eligible],
                      selected=eligible[:2], semantic_review='not_yet_reviewed')
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open('x') as stream:
            json.dump(record, stream, ensure_ascii=False, indent=2)
            stream.write('\n')
        population[case] = len(eligible)
    print(json.dumps(dict(completed_cases=len(population), eligible_by_case=population,
                          selected_count=sum(min(2, count) for count in population.values()))))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('--output', type=Path, required=True)
    sample(parser.parse_args().output)
