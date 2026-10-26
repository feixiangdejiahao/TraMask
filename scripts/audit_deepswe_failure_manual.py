"""Check the manual study's membership and literal evidence; never label gaps."""
from __future__ import annotations
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
STUDY=ROOT/'research/deepswe_failure_manual_20261006'


def strings(value):
    if isinstance(value,str):
        yield value
        if value.lstrip().startswith(('{','[')):
            try:decoded=json.loads(value)
            except ValueError:return
            if not isinstance(decoded,str):yield from strings(decoded)
    elif isinstance(value,dict):
        for item in value.values():yield from strings(item)
    elif isinstance(value,list):
        for item in value:yield from strings(item)


def coverage_ids(coverage):
    for key in ['operation_index_step_ids','all_public_step_ids_scanned','public_operation_index_reviewed']:
        value=coverage.get(key)
        if isinstance(value,list):return value
    for key in ['public_step_index','step_range']:
        value=coverage.get(key)
        if isinstance(value,list) and len(value)==2 and all(isinstance(x,int) for x in value):
            return list(range(value[0],value[1]+1))
    return None


def run(strict=False):
    protocol=json.loads((STUDY/'study_protocol.json').read_text())
    assignments=[r for rows in protocol['assignments'].values() for r in rows]
    expected={r['trial']:r for r in assignments}
    reports={p.stem:p for p in (STUDY/'trials').glob('*.json')}
    errors=[];checked=[]
    for trial,path in sorted(reports.items()):
        local=[]
        if trial not in expected:
            errors.append(dict(trial=trial,errors=['outside_frozen_cohort']));continue
        try:row=json.loads(path.read_text())
        except ValueError:
            errors.append(dict(trial=trial,errors=['report_not_complete_json']));continue
        for field in protocol['per_trial_fields']:
            if field not in row:local.append('missing_field:'+field)
        if row.get('trial')!=trial:local.append('trial_identity_mismatch')
        if row.get('verdict') not in protocol['trial_verdicts']:local.append('invalid_verdict')
        raw=ROOT/expected[trial]['raw_directory']
        document=json.loads((raw/'trajectory.json').read_text())
        trajectory_hash=hashlib.sha256((raw/'trajectory.json').read_bytes()).hexdigest()
        steps={s['step_id']:s for s in document['steps']}
        for name in ['trajectory.json','instruction.md','model.patch']:
            record=row.get('source_receipts',{}).get(name)
            if not record:
                local.append('missing_receipt:'+name);continue
            actual=hashlib.sha256((ROOT/record['path']).read_bytes()).hexdigest()
            if actual!=record['sha256']:local.append('source_hash_mismatch:'+name)
            if actual!=hashlib.sha256((raw/name).read_bytes()).hexdigest():local.append('wrong_trial_source:'+name)
        ids=coverage_ids(row.get('timeline_read_coverage',{}))
        if ids!=list(steps):local.append('full_operation_sequence_not_recorded')
        evidence=row.get('direct_evidence',[])
        if not evidence:local.append('no_literal_direct_evidence')
        for n,item in enumerate(evidence):
            sid=item.get('step_id');quote=item.get('excerpt',item.get('quote'))
            if sid not in steps:
                local.append(f'unknown_evidence_step:{n}:{sid}');continue
            if not isinstance(quote,str) or not quote:
                local.append(f'missing_evidence_quote:{n}');continue
            pool=list(strings(steps[sid]))
            if not any(quote in value for value in pool):
                normalized=' '.join(quote.split())
                if not any(normalized in ' '.join(value.split()) for value in pool):
                    local.append(f'evidence_quote_not_found:{n}:{sid}')
            stated=item.get('trajectory_sha256',item.get('raw_sha256'))
            if stated and stated!=trajectory_hash:local.append(f'evidence_trajectory_hash_mismatch:{n}')
        if local:errors.append(dict(trial=trial,errors=local))
        else:checked.append(dict(trial=trial,verdict=row['verdict'],report=str(path.relative_to(ROOT)),
                                report_sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
    pending=sorted(set(expected)-set(reports))
    summary=dict(status='complete_evidence_checks' if not errors and not pending else 'in_progress',
                 updated_utc=datetime.now(timezone.utc).isoformat(),expected_trials=len(expected),
                 reports_written=len(reports),literal_evidence_checks_passed=len(checked),
                 pending_trials=pending,errors=errors,checked_reports=checked,
                 descriptive_verdict_counts=dict(Counter(r['verdict'] for r in checked)),
                 validation_scope='Mechanical membership/hash/step/quote checks only. They do not independently confirm semantic judgments.',
                 completion_requires_all_trials=True,model_calls=0)
    (STUDY/'evidence_checkpoint.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:v for k,v in summary.items() if k not in ['pending_trials','errors','checked_reports']},ensure_ascii=False))
    if errors:print(json.dumps(errors,ensure_ascii=False))
    if strict and (errors or pending):raise SystemExit(1)
    return summary


if __name__=='__main__':
    parser=argparse.ArgumentParser(__doc__);parser.add_argument('--strict',action='store_true')
    run(parser.parse_args().strict)
