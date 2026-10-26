"""Complete HF001 direct-candidate evaluation after original outputs froze.

Default prepares exact Q and file maps only. --execute runs the two prepared
cells, six Q-only subject commands each. No provider, candidate rewrite, search,
retry, semantic verdict, or assumption that final P is correct.
"""
from concurrent.futures import ThreadPoolExecutor, as_completed
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from tramask_pilot.corpus import read, receipt
from tramask_rerun.study import RUN, now, write_new
from tramask_rerun.validation_material import load_validation_material, plan_validation
from run_tramask_direct_comparators import execute

Q = {
    'path': 'app/src/rules.ts',
    'old': '    return ignoreListOfTypes(this.ignoreTypes, text, (textAfterIgnore: string) => {',
    'new': "    return ignoreListOfTypes(this.ignoreTypes.filter((ignoreType) => ignoreType.placeholder !== '{LINTER_DISABLE_PLACEHOLDER}'), text, (textAfterIgnore: string) => {",
}


def prepare(rep):
    cell = RUN / 'runs/HF001/track_b/M1' / f'repeat_{rep:02d}'
    execution = cell / 'candidate_execution/rank_01'
    out = execution / 'evaluator_comparator_v01'
    if out.exists():
        raise FileExistsError('Existing comparator preparation retained')
    original_plan = read(execution / 'plan.json')
    case = original_plan['case']
    for bound in original_plan['bound_artifacts']:
        if receipt(bound['path']) != bound:
            raise ValueError('Original execution input changed')
    original_summary = read(execution / 'summary.json')
    if len(original_summary['runs']) != 6:
        raise ValueError('Frozen three-repeat P control and candidate results required')
    for run in original_summary['runs']:
        if receipt(run['result']['path']) != run['result']:
            raise ValueError('Frozen P execution result changed')
    slot = read(cell / 'stage_02/candidate_slots.json')['slots'][0]
    if slot['status'] != 'proposed' or not slot['structural_valid']:
        raise ValueError('Original submitted valid slot required')
    planning = read(cell / 'stage_01/planning.json')
    if planning['target']['source_path'] != Q['path']:
        raise ValueError('Comparator must match independently selected Rule.apply mechanism')
    material = load_validation_material(receipt(cell / 'stage_01/public_input.json'),
        original_plan['staged']['inventory_receipt'], planning['selected_test_id'],
        checkpoint_proof_receipt=case['checkpoint']['summary'],
        terminal_export_receipts=[receipt(RUN / 'runs/HF001/terminal_sources/result.json')])
    qpath = out / 'fixed_evaluator_Q.json'
    write_new(qpath, {
        'created_at': now(), 'role': 'post-output independent evaluation comparator',
        'edits': [Q],
        'contract_to_review_independently': 'The selected Rule.apply test requires scoped trailing-spaces disable markers to protect the enclosed line. Exclude only the linterDisable ignore type by its exact existing placeholder from Rule.apply; preserve all other ignore types, target input, registration and original observations/assertions.',
        'issue': receipt(RUN / 'inputs/HF001/instruction.md'),
        'selected_target': receipt(cell / 'stage_01/planning.json'),
        'candidate_frozen_before_construction': receipt(cell / 'stage_02/canonical_candidates.json'),
        'P_results': receipt(execution / 'summary.json'),
        'not_given_to_generator': True, 'Q_may_be_correct_or_incorrect_until_review': True,
        'researcher_exposure': 'Root constructed this single evaluator comparator after the two direct outputs, their P executions and prior neutral reviews froze. Root has seen prior reference/evaluation work. This is disclosed post-freeze evaluation, not blind gold construction or a new generation replicate.',
        'selection_rule': 'Both already-generated legal context-only HF001/M1 candidates without a Q comparator are evaluated, irrespective of observed Q outcomes. One exact same local Q per cell; no alternate-Q retry.',
        'scientific_label': None,
    })
    staged = plan_validation(material, slot['candidate'], fixed_q_receipt=receipt(qpath),
        frozen_output_receipt=receipt(cell / 'stage_02/canonical_candidates.json'))
    for name in ['p_original', 'p_candidate']:
        if staged['arms'][name] != original_plan['staged']['arms'][name]:
            raise ValueError('Comparator preparation altered original P arm or submitted candidate')
    if any(staged['arms'][name]['build_steps'] for name in ['q_original', 'q_candidate']):
        raise ValueError('Only original source-transform Jest runner allowed')
    write_new(out / 'plan.json', {'case': case, 'staged': staged, 'created_at': now(), 'repeats': 3,
        'independent_evaluation_cost_not_generation': True,
        'previous_P_control_and_candidate_results': receipt(execution / 'summary.json'),
        'subject_run_cap': 6, 'additional_provider_calls': 0,
        'implementation': [receipt(Path(__file__)), receipt(ROOT / 'scripts/run_tramask_direct_comparators.py'),
            receipt(ROOT / 'src/tramask_rerun/validation_material.py'), receipt(ROOT / 'src/tramask_rerun/runtime.py')]})
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args()
    if not args.execute:
        for rep in [1, 2]:
            out = prepare(rep)
            print(json.dumps({'plan': receipt(out / 'plan.json'), 'executed': False}), flush=True)
        return
    freeze = read(RUN / 'amendments/018_hf001_postfreeze_evaluator.json')
    for bound in freeze['implementation'] + freeze['plans']:
        if receipt(bound['path']) != bound:
            raise ValueError('Frozen evaluator implementation/plan changed')
    with ThreadPoolExecutor(max_workers=2) as pool:
        pending = {pool.submit(execute, Path(bound['path']).parent): bound for bound in freeze['plans']}
        for future in as_completed(pending):
            result = future.result()
            print(json.dumps({'plan': pending[future], 'status': result['status'], 'runs': len(result['runs'])}), flush=True)


if __name__ == '__main__':
    main()
