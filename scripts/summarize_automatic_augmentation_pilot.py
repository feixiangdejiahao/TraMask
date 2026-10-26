"""Join frozen model records and independent audits; fail on missing candidates."""
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import run_automatic_augmentation_pilot as base
from scripts import run_automatic_augmentation_io_repair as io

RESULTS = ROOT / 'results/automatic_augmentation_pilot_20261005'
RESEARCH = ROOT / 'research'


def count_rows(rows):
    supported = [r for r in rows if r['oracle_status'] == 'supported']
    combination = [r for r in supported if r['combination_increment'] == 'yes']
    return dict(candidates=len(rows), oracle=dict(Counter(r['oracle_status'] for r in rows)),
                combination=dict(Counter(r['combination_increment'] for r in rows)),
                execution=dict(Counter(r['execution_status'] for r in rows)),
                supported_combination=len(combination),
                supported_combination_passed=sum(r['execution_status'] == 'passed' for r in combination),
                supported_combination_failed=sum(r['execution_status'] == 'controlled_failure' for r in combination),
                supported_non_combination=len(supported) - len(combination),
                supported_observation_strengthening=sum(r.get('increment_class') == 'oracle_strengthening_existing_combination' for r in supported),
                primary_target_test_instances=sum(bool(r['primary_target_hit']) for r in supported),
                primary_target_cases=sorted({r['case'] for r in supported if r['primary_target_hit']}))


def rounds(name, directory, audit_rows):
    results = []
    expected = []
    for path in sorted(directory.glob('cases/*/*/*/*/result.json')):
        base.verify(base.read(path.with_name('result_seal.json')))
        result = base.read(path)
        for key in ('judgment', 'decoded'):
            if key in result:
                base.verify(result[key])
        results.append(result)
        if 'decoded' in result:
            for candidate in base.read(result['decoded']['path'])['candidates']:
                expected.append((result['case'], result['batch'], result['arm'], result['repeat'], candidate['id']))
    if len(results) != 48:
        raise ValueError(f'{name}:incomplete_model_work:{len(results)}')
    actual = [(r['case'], r['batch'], r['arm'], r['repeat'], r['candidate_id']) for r in audit_rows]
    if Counter(expected) != Counter(actual) or any(n != 1 for n in Counter(actual).values()):
        raise ValueError(f'{name}:candidate_audit_membership_mismatch:{len(expected)}:{len(actual)}')
    native_groups = 0
    controls_passed = True
    for row in audit_rows:
        base.verify(row['source_audit_receipt'])
        base.verify(row['native_receipt'])
        native = base.read(row['native_receipt']['path'])
        if native['candidate_id'] != row['candidate_id']:
            raise ValueError('native_candidate_identity_mismatch')
        observed = {outcome['status'] for outcome in native['outcomes']}
        if row['execution_status'] in {'passed', 'controlled_failure'} and observed != {row['execution_status']}:
            raise ValueError('native_outcome_disagrees_with_audit')
        if row['execution_status'] == 'controlled_failure' and not native['repeated_controlled_failure']:
            raise ValueError('failure_not_reproduced')
        for outcome in native['outcomes']:
            base.verify(outcome['receipt'])
            controls_passed &= outcome.get('native', {}).get('controls', {}).get('status') == 'all_source_controls_passed'
        native_groups += len(native['outcomes'])
        if row.get('classification_correction'):
            base.verify(row['classification_correction'])
    manifests = [base.read(p) for p in directory.glob('cases/*/*/*/*/*/completion/manifest.json')]
    calls = sum(m.get('external_model_calls', 0) for m in manifests)
    tokens = sum((m.get('usage') or {}).get('total_tokens', 0) for m in manifests)
    if calls != sum(r['provider_calls'] for r in results) or tokens != sum(r['measured_tokens'] for r in results):
        raise ValueError('provider_accounting_mismatch')
    issues = Counter()
    rejected = Counter()
    for row in results:
        issues.update(base.read(row['judgment']['path'])['issues'])
        rejected.update(r['reason'] for r in row.get('rejected', []))
    summary = dict(name=name, work_items=48,
                   judgment_status=dict(Counter(r['judgment_status'] for r in results)),
                   generation_status=dict(Counter(r['generation_status'] for r in results)),
                   judgment_issues=dict(issues), generation_rejections=dict(rejected),
                   provider_calls=calls, measured_tokens=tokens,
                   usage_missing=sum(r['usage_missing'] for r in results),
                   response_models=sorted({m.get('response_model') for m in manifests if m.get('response_model')}),
                   evaluation=count_rows(audit_rows),
                   native_execution_groups=native_groups,
                   all_authoritative_native_controls_passed=controls_passed)
    summary['by_arm'] = {}
    for arm in base.ARMS:
        model_rows = [r for r in results if r['arm'] == arm]
        summary['by_arm'][arm] = dict(
            judgments=dict(Counter(r['judgment_status'] for r in model_rows)),
            provider_calls=sum(r['provider_calls'] for r in model_rows),
            measured_tokens=sum(r['measured_tokens'] for r in model_rows),
            **count_rows([r for r in audit_rows if r['arm'] == arm]))
    summary['by_case'] = {case: count_rows([r for r in audit_rows if r['case'] == case]) for case in base.CASES}
    summary['rows'] = audit_rows
    return summary


def run():
    io.load_protocol(io.DEFAULT_OUTPUT)
    n_path = RESEARCH / 'automatic_augmentation_audit_n_20261005.json'
    p_path = RESEARCH / 'automatic_augmentation_strict_audit_p_20261005.json'
    n_io = RESEARCH / 'automatic_augmentation_audit_n_io_repair_20261005.json'
    p_io = RESEARCH / 'automatic_augmentation_io_repair_audit_p_20261005.json'
    rows = []
    for r in base.read(n_path)['joined_candidates']:
        rows.append(dict(case=r['case'], batch=r['batch'], arm=r['arm'], repeat=r['repeat'],
                         rank=r['candidate_index'], candidate_id=r['candidate_id'],
                         oracle_status=r['source_first_status'],
                         combination_increment='yes' if r['valid_combination_increment'] else 'unknown' if r['source_first_status'] == 'unknown' else 'no',
                         primary_target_hit=r['predeclared_target_match'],
                         execution_status='controlled_failure' if 'controlled_failure' in r['native_statuses'] else 'passed',
                         source_audit_receipt=r['source_audit'], native_receipt=r['native'],
                         increment_class=r['increment_class'], reason=r['increment_explanation']))
    for r in base.read(p_path)['candidates']:
        base.verify(r['dynamic_audit'])
        # Locate the authoritative native receipt from the same frozen source
        # audit's generation directory; native_result contains both repeats.
        native = Path(r['source_audit']['path']).parent / 'native' / f"candidate_{r['rank']:02d}" / 'native_result.json'
        rows.append(dict(case=r['case'], batch='B01', arm=r['arm'], repeat=r['repeat'],
                         rank=r['rank'], candidate_id=r['candidate_id'], oracle_status=r['complete_oracle'],
                         combination_increment='yes' if r['combination_increment'] else 'unknown' if r['complete_oracle'] == 'unknown' else 'no',
                         primary_target_hit=r['primary_positive_target_hit'],
                         execution_status='controlled_failure' if r['native_status'] == 'supported_repeated_failure' else 'passed',
                         source_audit_receipt=r['source_audit'], native_receipt=base.receipt(native),
                         increment_class=r['increment_class'], reason=r['native_status']))
    strict = rounds('strict', RESULTS, rows)
    repair = rounds('io_repair_v2', io.DEFAULT_OUTPUT, base.read(n_io)['rows'] + base.read(p_io)['rows'])
    judgment_path = RESEARCH / 'automatic_augmentation_judgment_audit_20261005.json'
    judgment = base.read(judgment_path)
    if any(r['completion'] != 'complete' for r in judgment['rounds']):
        raise ValueError('judgment_review_incomplete')
    output = dict(version='automatic-augmentation-closeout.v1', status='main_complete',
                  created_utc=datetime.now(timezone.utc).isoformat(),
                  selection='Six purposefully selected development-seen trajectories across five tasks.',
                  main_is_automatic=True, evaluation_includes_human_review=True,
                  all_main_candidates_accounted_for=True,
                  evidence=[base.receipt(p) for p in [n_path, p_path, n_io, p_io, judgment_path]],
                  extraction=base.read(RESEARCH / 'automatic_augmentation_extraction_audit_20261005.json')['summary'],
                  rounds=[strict, repair],
                  judgment_counts={r['round']: r['counts'] for r in judgment['rounds']},
                  model_calls_total=strict['provider_calls'] + repair['provider_calls'],
                  measured_tokens_total=strict['measured_tokens'] + repair['measured_tokens'],
                  diagnostics='Separate goal/context diagnostic artifacts; excluded from all main scores.')
    dest = RESEARCH / 'automatic_augmentation_pilot_results_20261005.json'
    base.write(dest, output)
    base.write(dest.with_name(dest.stem + '_seal.json'), base.receipt(dest))
    print(base.canonical({k: v for k, v in output.items() if k not in {'rounds', 'evidence', 'extraction', 'judgment_counts'}}))


if __name__ == '__main__':
    run()
