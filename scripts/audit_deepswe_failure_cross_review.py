"""Check second-review receipts, membership and completeness; never infer semantics."""
from collections import Counter
from datetime import datetime, timezone
import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STUDY = ROOT / 'research/deepswe_failure_manual_20261006'
CROSS = STUDY / 'cross_review'


def read(path):
    return json.loads(path.read_text())


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(strict=False):
    protocol = read(CROSS / 'protocol.json')
    expected = set(read(STUDY / 'cohort_audit.json')['trial_names'])
    assignments = {}
    for path in CROSS.glob('*_assignment.json'):
        reviewer = '/root' if path.name == 'root_assignment.json' else '/root/' + path.name.removesuffix('_assignment.json')
        for row in read(path):
            assert row['trial'] not in assignments
            assignments[row['trial']] = (reviewer, row)
    assert set(assignments) == expected and len(expected) == 211
    reports = {p.stem:p for p in (CROSS / 'trials').glob('*.json')}
    accepted, issues = [], []
    statuses = Counter()
    for trial, path in sorted(reports.items()):
        errors = []
        if trial not in assignments:
            issues.append({'trial':trial, 'errors':['outside_frozen_cohort']})
            continue
        try:
            row = read(path)
        except ValueError:
            issues.append({'trial':trial, 'errors':['cross_report_incomplete_json']})
            continue
        reviewer, source = assignments[trial]
        primary = STUDY / 'trials' / (trial + '.json')
        for field in protocol['result_fields']:
            if field not in row:
                errors.append('missing_field:' + field)
        if row.get('trial') != trial:
            errors.append('trial_identity_mismatch')
        if row.get('reviewer') != reviewer or row.get('primary_reviewer') != source['primary_reviewer']:
            errors.append('reviewer_assignment_mismatch')
        if row.get('reviewer') == row.get('primary_reviewer'):
            errors.append('self_review')
        receipt = row.get('primary_report_receipt', {})
        if not primary.exists():
            errors.append('primary_report_missing')
        elif not receipt.get('path') or (ROOT / receipt['path']).resolve() != primary.resolve() or receipt.get('sha256') != digest(primary):
            errors.append('primary_report_changed_or_wrong_receipt')
        raw = ROOT / source['raw_directory']
        for name in ['instruction.md', 'trajectory.json', 'model.patch']:
            rec = row.get('source_receipts', {}).get(name, {})
            if not rec.get('path') or (ROOT / rec['path']).resolve() != (raw / name).resolve() or rec.get('sha256') != digest(raw / name):
                errors.append('wrong_original_source_receipt:' + name)
        if not row.get('inspection_scope'):
            errors.append('no_actual_inspection_scope_recorded')
        if not row.get('claim_checks'):
            errors.append('no_substantive_claim_checks_recorded')
        status = row.get('status')
        if status not in protocol['statuses']:
            errors.append('invalid_status')
        statuses[str(status)] += 1
        if errors:
            issues.append({'trial':trial, 'errors':errors})
        elif status == 'accepted':
            accepted.append({'trial':trial, 'reviewer':reviewer, 'primary_report_sha256':receipt['sha256'],
                             'cross_report':str(path.relative_to(ROOT)), 'cross_report_sha256':digest(path)})
        else:
            issues.append({'trial':trial, 'errors':['semantic_review_not_accepted'], 'status':status})
    pending = sorted(expected - set(reports))
    summary = {
        'updated_utc':datetime.now(timezone.utc).isoformat(),
        'status':'all_receipts_current' if not pending and not issues else 'in_progress',
        'expected_trials':211, 'cross_reports_saved':len(reports), 'current_accepted_receipts':len(accepted),
        'status_counts':dict(statuses), 'pending_trials':pending, 'issues':issues,
        'accepted_reports':accepted,
        'validation_scope':'Mechanical validation of manually written semantic signoffs only. It does not independently validate the substantive claims or prove that the overall study is complete.',
        'model_calls':0,
    }
    (CROSS / 'evidence_checkpoint.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:v for k,v in summary.items() if k not in ['pending_trials','issues','accepted_reports']},ensure_ascii=False))
    if issues:
        print(json.dumps(issues,ensure_ascii=False))
    if strict and (pending or issues):
        raise SystemExit(1)
    return summary


if __name__ == '__main__':
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('--strict', action='store_true')
    run(parser.parse_args().strict)
