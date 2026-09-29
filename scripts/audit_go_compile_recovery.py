"""Read-only execution accounting for the independent compile-error supplement."""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from relation_search.checkpoint import digest, read, write
from scripts.replay_go_compile_failures import value_sha


def audit(plan_path, output):
    plan_path, output = Path(plan_path), Path(output)
    plan = read(plan_path)
    rows, groups = [], []
    for entry in plan['groups']:
        folder = output/entry['id']
        if not (folder/'executed/runs.json').exists():
            continue
        candidates = read(folder/'prepared/candidates.json')['candidates']
        assert {row['id']: value_sha(row) for row in candidates} == entry['candidate_sha256']
        old_rows = [row for row in read(Path(entry['original_execution'])/'runs.json')
                    if row['manifest'] == entry['origin_manifest'] and row['role'] == 'generated']
        old_by_id = {row['candidate_id']: row for row in old_rows}
        current = read(folder/'executed/runs.json')
        controls = {}
        for row in current:
            if row['role'] != 'control':
                continue
            report = read(Path(row['result']))
            valid = report['status'] == 'pass' and not report['errors'] and report['counts']['pass'] > 0
            for name in row['test_ids']:
                controls[(row['manifest'], name)] = valid
        for row in current:
            if row['role'] != 'generated':
                continue
            cid = row['candidate_id']
            raw = read(Path(row['result']).parent/'result.json')
            report = read(Path(row['result']))
            original = read(Path(old_by_id[cid]['result']).parent/'result.json')
            blocked = original.get('isolation_status') == 'not_run' and original.get('isolation_reason') == 'compile_error'
            executed = raw.get('isolation_status') in {'pass', 'fail'} and not report['errors']
            control_ok = bool(row['control_ids']) and all(controls.get((row['manifest'], name), False)
                                                        for name in row['control_ids'])
            rows.append(dict(case=entry['case'], original_group=entry['id'], candidate_id=cid,
                originally_compile_blocked=blocked, recovered_named_execution=blocked and executed,
                named_execution=executed, status=raw.get('isolation_status'), reason=raw.get('isolation_reason'),
                all_source_controls_pass=control_ok, recovered_with_passing_controls=blocked and executed and control_ok,
                result=row['result'], result_sha256=digest(row['result']),
                manifest=row['manifest'], unchanged_candidate_json=True))
        groups.append(dict(id=entry['id'], case=entry['case'], planned=len(entry['candidate_ids']),
                           recorded_generated=sum(row['role'] == 'generated' for row in current),
                           sealed=(folder/'executed/checkpoint.json').exists()))
    def summarize(members):
        return dict(recorded=len(members), named_execution=sum(row['named_execution'] for row in members),
            recovered_named_execution=sum(row['recovered_named_execution'] for row in members),
            recovered_with_passing_controls=sum(row['recovered_with_passing_controls'] for row in members),
            still_compile_error=sum(row['reason'] == 'compile_error' for row in members),
            all_source_controls_pass=sum(row['all_source_controls_pass'] for row in members),
            statuses=dict(Counter(row['status'] for row in members)),
            reasons=dict(Counter(row['reason'] for row in members if row['reason'])))
    return dict(policy='compile-recovery-execution-only-v1', observed_utc=datetime.now(timezone.utc).isoformat(),
        plan_sha256=digest(plan_path), planned=plan['candidates'], completed_original_groups=sum(row['sealed'] for row in groups),
        counts=summarize(rows), by_case={case:summarize([row for row in rows if row['case']==case])
                                      for case in sorted({row['case'] for row in rows})},
        groups=groups, rows=rows, semantic_correctness='not assessed', main_campaign_credit=0)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('--plan', type=Path, required=True)
    parser.add_argument('--execution', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError('Audit snapshot must be new')
    result = audit(args.plan, args.execution)
    write(args.output, result)
    print(result['counts'])
