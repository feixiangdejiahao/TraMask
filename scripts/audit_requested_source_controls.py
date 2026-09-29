"""Associate already dispatched oracle requests with later source-control runs.

This is an observational audit only: it does not run subjects, filter generation,
or count any main target. Missing runs remain explicit rather than inferred.
"""
from __future__ import annotations

import argparse
from collections import Counter
from functools import lru_cache
import hashlib
import json
from pathlib import Path

from evaluate_relational_gap import matches_runtime, runtime_tests


def read(path):
    return json.loads(Path(path).read_text())


@lru_cache(None)
def native(path):
    return runtime_tests(Path(path))


def inspect_controls(generated, runs):
    evidence = []
    missing = []
    for generated_row in generated:
        for name in generated_row.get('control_ids', []):
            controls = [r for r in runs if r['role'] == 'control'
                        and r['manifest'] == generated_row['manifest'] and name in r['test_ids']]
            if not controls:
                missing.append(name)
            for control in controls:
                tests, errors, _ = native(control['result'])
                matched = [test for test in tests if matches_runtime(test['id'], name)]
                if not matched or errors:
                    missing.append(name)
                evidence.append(dict(control_id=name, base_test_id=control['base_test_id'],
                    result=control['result'], statuses=[t['status'] for t in matched],
                    parser_errors=errors, messages=[t.get('message', '')[:1000] for t in matched if t['status'] != 'pass']))
    statuses = [s for row in evidence for s in row['statuses']]
    if not generated:
        status = 'no_matching_emitted_candidate'
    elif missing or not evidence:
        status = 'missing_or_unparseable_controls'
    elif any(s in {'fail', 'error'} for s in statuses):
        status = 'source_control_failed_or_errored'
    elif any(s != 'pass' for s in statuses):
        status = 'source_control_skipped_or_other'
    else:
        status = 'all_source_controls_passed'
    return dict(status=status, missing=sorted(set(missing)), controls=evidence)


def audit(campaign):
    rows = []
    for request_path in sorted(Path(campaign).glob('*/round_*/semantic/requests/request_*.json')):
        round_dir = request_path.parents[2]
        completion = request_path.parent.parent / 'completions' / request_path.stem
        if not (completion / 'manifest.json').exists():
            continue
        manifest = read(completion / 'manifest.json')
        if manifest.get('external_model_calls') != 1:
            continue
        run_path = round_dir / 'executed/runs.json'
        runs = read(run_path) if run_path.exists() else None
        for item in read(request_path)['offered'].values():
            cid = item['candidate']['id']
            generated = [r for r in (runs or []) if r['role'] == 'generated' and r.get('candidate_id') == cid]
            result = inspect_controls(generated, runs) if runs is not None else dict(status='round_execution_not_recorded', missing=[], controls=[])
            rows.append(dict(case=round_dir.parent.name, round=round_dir.name,
                             candidate_id=cid, request=str(request_path),
                             dispatch_created_at=manifest.get('created_at'),
                             provider_finish_reason=manifest.get('finish_reason'),
                             runs_sha256=hashlib.sha256(run_path.read_bytes()).hexdigest() if runs is not None else None,
                             **result))
    cases = {}
    for case in sorted({r['case'] for r in rows}):
        cases[case] = dict(Counter(r['status'] for r in rows if r['case'] == case))
    return dict(protocol='Exact offered candidate -> emitted generated row -> same-manifest named source controls. All parameter instances must pass. No subject or model calls; no target-score changes.',
                audit_code_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                dispatched_candidate_occurrences=len(rows),
                counts=dict(Counter(r['status'] for r in rows)), cases=cases, rows=rows)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('--campaign', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = audit(args.campaign)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x') as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
    print(json.dumps({k: v for k, v in result.items() if k != 'rows'}, ensure_ascii=False))
