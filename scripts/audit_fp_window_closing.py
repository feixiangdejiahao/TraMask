"""Read-only closing inventory: provider budget, retained baseline, source seals.

Reads usage receipts and existing aggregate evaluations only. It never imports
the provider/subject runners or opens heldout manual-review labels.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
WINDOW = ROOT / 'results/fp_reduction_20261002'
BASELINE = '7a8ff9521a898bb6ff90f29719e78cabf9964cc6'
BASELINE_TAG = 'fp-restart-20261002-detection-baseline'
MIXED_SOURCE_RECEIPT = WINDOW/'mixed_value_state_source_opportunities_v1.json'
MIXED_SOURCE_SHA256 = 'cdc586cefbe01b59671d43e3e7ba60cfc67dc0b8b5ad27d6956ee53a0aed3f78'
DEADLINE_UTC = datetime(2026,10,2,18,7,24,tzinfo=timezone.utc)


def read(path):
    return json.loads(Path(path).read_text())


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def ref(path):
    path = Path(path).resolve()
    return dict(path=str(path), sha256=sha(path))


def require(value, message):
    if not value:
        raise ValueError(message)


def verify(row):
    require(Path(row['path']).is_file() and sha(row['path']) == row['sha256'], 'Receipt changed: '+row['path'])


def git(*args):
    return subprocess.check_output(['git', *args], cwd=ROOT, text=True).strip()


def provider_budget():
    ledger_path = WINDOW/'independent_budget_through_compact_v6.json'
    ledger = read(ledger_path)
    rows = []; known_paths = set(); latest = None
    for entry in ledger['runs']:
        verify(entry['summary']); summary = read(entry['summary']['path'])
        measured = reserve = missing = calls = 0
        for sealed in entry['receipt_hashes']:
            verify(sealed); path = Path(sealed['path']).resolve(); known_paths.add(path)
            completion = read(path); calls += completion['external_model_calls']
            created = completion['created_at']; latest = max(latest, created) if latest else created
            usage = completion.get('usage', {})
            if isinstance(usage.get('total_tokens'), int):
                measured += usage['total_tokens']
            elif isinstance(usage.get('prompt_tokens'), int) and isinstance(usage.get('completion_tokens'), int):
                measured += usage['prompt_tokens']+usage['completion_tokens']
            else:
                request = read(path.parent.parent/'request.json')
                reserve += len(request['system'].encode())+len(request['prompt'].encode())+request['max_tokens']+256
                missing += 1
        require(calls == entry['provider_requests'] == summary['provider_calls'], 'Provider call count mismatch')
        require(measured == entry['known_measured_tokens'], 'Measured provider usage mismatch')
        require(reserve == entry['conservative_missing_usage_reserve'], 'Missing-usage reservation mismatch')
        require(measured+reserve == entry['accounted_tokens'] == summary['accounted_tokens'], 'Accounted usage mismatch')
        require(missing == entry['missing_usage_requests'] == summary['usage_missing'], 'Missing usage count mismatch')
        rows.append(dict(run=entry['run'], summary=entry['summary'], calls=calls, measured=measured,
                         missing_reserve=reserve, accounted=measured+reserve, missing_usage_calls=missing))
    discovered = {path.resolve() for path in WINDOW.glob('*/item_*/completion/manifest.json')}
    require(discovered == known_paths, 'Unaccounted or missing completion receipt in current window')
    totals = dict(calls=sum(row['calls'] for row in rows), measured=sum(row['measured'] for row in rows),
                  missing_reserve=sum(row['missing_reserve'] for row in rows), accounted=sum(row['accounted'] for row in rows),
                  missing_usage_calls=sum(row['missing_usage_calls'] for row in rows))
    require(totals == dict(calls=163,measured=1053004,missing_reserve=411052,accounted=1464056,missing_usage_calls=22),
            'Window changed from requested closing snapshot')
    return dict(ledger=ref(ledger_path), runs=rows, totals=totals, cap=1500000, remaining=1500000-totals['accounted'],
        completion_receipts_verified=len(known_paths), unaccounted_completion_receipts=0, latest_receipt_created_at=latest,
        scope='All completion manifests at window/*/item_*/completion/manifest.json; does not claim proof about unreceipted external activity.',
        missing_usage_policy='All22 prior missing-usage calls retain their full byte-bound reservations; no assumed-zero HTTP400 refund.')


def source_census(name):
    root = WINDOW/name; manifest_path = root/'manifest.json'; manifest = read(manifest_path)
    outcome_path = root/'independent_outcome.json'; outcome = read(outcome_path)
    verify(outcome['manifest'])
    snapshots = manifest.get('source_snapshots') or outcome['frozen_source_snapshots']
    for snapshot in snapshots:
        require(sha(snapshot['snapshot']) == snapshot['sha256'], 'Frozen source snapshot changed')
    artifact_count = 0; output_candidates = 0
    for case in manifest['cases']:
        for variant in case['variants'].values():
            for field in ('output','independent_audit'):
                verify(variant[field]); artifact_count += 1
            result = read(variant['output']['path'])
            require(result['provider_calls'] == result['native_executions'] == 0, 'Source census execution claim changed')
            output_candidates += len(result['candidates'])
    for field in ('inventory','protocol'):
        verify(manifest[field])
    require(len(manifest['cases']) == 17 and output_candidates == 0, 'Census denominator or output changed')
    return dict(manifest=ref(manifest_path),outcome=ref(outcome_path),source_snapshot_count=len(snapshots),
                artifact_hashes_verified=artifact_count,cases=17,emitted_candidates=output_candidates,
                provider_calls=0,native_executions=0,promoted=False)


def phase_state(now, deadline, phase='interim'):
    """Validate the actual clock boundary; never sleep or imply quality success."""
    require(phase in {'interim','final'}, 'Unknown closing phase')
    require(now.tzinfo is not None and deadline.tzinfo is not None, 'Closing times must be timezone-aware')
    if phase == 'interim':
        require(now < deadline, 'Interim phase requires a time strictly before the deadline')
    else:
        require(now >= deadline, 'Final phase requires a time at or after the deadline; no automatic wait')
    return dict(phase=phase,status='interim_before_deadline' if phase=='interim' else 'final_at_or_after_deadline',
        bounded_window_finished=phase=='final',objective_achieved=False,quality_objective_achieved=False,
        deadline_utc=deadline.isoformat(),seconds_to_deadline=(deadline-now).total_seconds())


def build(phase='interim'):
    now = datetime.now(timezone.utc)
    restart_path = ROOT/'research/fp_reduction_restart_20261002.json'; restart = read(restart_path)
    deadline = datetime.fromisoformat(restart['deadline_utc'].replace('Z','+00:00'))
    require(deadline == DEADLINE_UTC, 'Window deadline differs from the authorized closing boundary')
    state = phase_state(now,deadline,phase)
    require(git('rev-parse', BASELINE_TAG) == BASELINE, 'Retained baseline tag moved')
    subprocess.run(['git','merge-base','--is-ancestor',BASELINE,'HEAD'],cwd=ROOT,check=True)
    evaluation_path = ROOT/'results/relation_search_20260929_v3/evaluation/uniform_fresh_impact_v3/checkpoint_14.json'
    evaluation = read(evaluation_path)
    require(evaluation['denominator'] == 17 and evaluation['counts']['fixed_configuration_correct'] == 16,
            'Historical baseline aggregate changed')
    inventory_path = WINDOW/'observation_action_source_inventory_v1.json'; inventory = read(inventory_path)
    for case in inventory['cases']:
        for kind in ('corpus','frontend'):
            verify(case[kind])
    prior_reference = ROOT/'research/fp_reduction_timebox_outcome_20261001.json'
    # Experiments have isolated entry points; no import into normal search or admission packages.
    production_references = []
    for directory in ('relation_search','relational_gap','generic_composition'):
        for path in (ROOT/directory).rglob('*.py'):
            code = path.read_text()
            if 'observation_address_join' in code or 'observation_address_search' in code:
                production_references.append(str(path.relative_to(ROOT)))
    require(not production_references, 'Address prototype referenced from production package')
    mixed_source = dict(path=str(MIXED_SOURCE_RECEIPT.resolve()),sha256=MIXED_SOURCE_SHA256)
    verify(mixed_source)
    return dict(version='independent-fp-window-closing-audit.v2',created_utc=now.isoformat(),**state,
        claim='No demonstrated FP improvement satisfying the retained >=16/17 task-witness requirement. '+
            ('The bounded window has finished; the quality objective remains unmet.' if phase=='final'
             else 'This receipt closes an interim snapshot; the bounded window continues and the quality objective remains unmet.'),
        auditor=ref(__file__),restart_protocol=ref(restart_path),budget=provider_budget(),
        baseline=dict(tag=BASELINE_TAG,commit=BASELINE,tag_resolves_correctly=True,ancestor_of_head=True,
            archived_evaluation=ref(evaluation_path),archived_fixed_configuration_correct=16,task_denominator=17,
            prior_reference_record=ref(prior_reference),fresh_subject_reproduction_performed=False,
            interpretation='Preserved historical canonical baseline; preservation is not a new16/17 run and is not precision of every emitted alarm.'),
        source_inventory=ref(inventory_path),source_input_receipts_verified=34,
        source_experiments=[source_census(name) for name in ('observation_address_source_census_v1','observation_address_source_census_v2')],
        mixed_source_opportunity_census=dict(receipt=mixed_source,
            interpretation='Verified receipt bytes only; source opportunity is not generated-candidate validity, runtime influence, or fault-detection evidence.'),
        promotion=dict(v1=False,v2=False,production_package_references=production_references,
            evidence_scope='No address-prototype reference in relation_search, relational_gap or generic_composition packages; historical baseline tag retained. Experimental standalone runners remain available.'),
        repository_head=git('rev-parse','HEAD'),provider_calls_by_auditor=0,native_executions_by_auditor=0,
        heldout_manual_labels_opened=False,threshold_tuning_recommended=False,
        reproduction_limit='Receipt/hash and existing aggregate audit only. No provider or subject rerun; source research may add artifacts after this timestamp.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(__doc__); parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--phase',choices=('interim','final'),default='interim',
                        help='Interim only before deadline; final only at/after deadline. Never waits.')
    args = parser.parse_args(); report = build(args.phase);args.output.parent.mkdir(parents=True,exist_ok=True)
    with args.output.open('x') as stream:
        json.dump(report,stream,indent=2);stream.write('\n')
    print(json.dumps(dict(output=ref(args.output),created_utc=report['created_utc'],budget=report['budget']['totals'],
                         remaining=report['budget']['remaining'],status=report['status'])))
