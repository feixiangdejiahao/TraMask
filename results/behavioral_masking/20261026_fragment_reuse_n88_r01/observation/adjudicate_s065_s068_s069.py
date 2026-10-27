"""Root source adjudications, outside blind inputs."""
from pathlib import Path
import copy
import hashlib
import json

OBS = Path(__file__).resolve().parent
RUN = OBS.parent


def read(p):
    return json.loads(p.read_text())


def receipt(p):
    raw = p.read_bytes()
    return {'path': str(p), 'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}


for cid in ['S065', 'S068', 'S069']:
    reviews = {r: read(OBS / f'reviewer_{r}/{cid}.json') for r in ['A', 'B']}
    a, b = reviews['A'], reviews['B']
    sources = read(OBS / f'sources/{cid}.json')['sources']
    actions = {x['id']: x for x in read(RUN / f'public_inputs/{cid}/history.json')['actions']}
    frozen = {}
    for role in ['A', 'B']:
        dst = OBS / f'frozen_reviews/{role}/{cid}.json'
        dst.parent.mkdir(parents=True, exist_ok=True)
        with dst.open('xb') as stream:
            stream.write((OBS / f'reviewer_{role}/{cid}.json').read_bytes())
        frozen[role] = {'path': str(dst.relative_to(RUN)), 'sha256': receipt(dst)['sha256']}
    primary = b if cid == 'S065' else a
    d = {k: copy.deepcopy(primary[k]) for k in ['case_id', 'trial', 'task', 'known_case',
        'target_operation', 'required_factor_inventory', 'agent_base_units',
        'missing_factors', 'oracle_availability']}
    d.update(schema_version='fragment-observation-adjudication.v1', status='complete',
             adjudicator='Codex /root', reviews=frozen)
    d['minimal_assembly'] = {
        'proposed_source_units': primary['minimal_assembly']['distinct_historical_source_units_including_base'],
        'proposed_transferred_fragments': primary['minimal_assembly']['transferred_fragments'],
        'new_semantic_elements': primary['minimal_assembly']['new_semantic_elements'],
        'new_external_primitive_knowledge': 1 if cid == 'S069' else 0,
        'source_proposals': {r: copy.deepcopy(x['minimal_assembly']) for r, x in reviews.items()},
        'execution_validated_minimum': None,
    }
    d['historical_joint_witness'] = {'complete_assertion_witness': False}
    d['execution'] = {'status': 'not_executed_in_this_study',
                      'manual_assembly_success': False, 'blind_result': False}
    notes = d['adjudication_notes'] = []
    if cid == 'S065':
        notes.extend([
            {'topic': 'agreement on the actual miss', 'resolution': 'Both reviewers select the same Invalid.lash call and wrong no-op expected result.95 defines the full test;110 runs27tests successfully. The trigger, callback and error tuple are already present; the missing factor is a correct Check.'},
            {'topic': 'trusted expectation without executed donor', 'resolution': 'Original8 reads Result.lash documentation showing failure recovery to Success, and Issue requires FailableN integration. These are available contract/source clues, not executed Validated recovery tests.110 doctests cover validated and selected converters/pointfree modules, not the read Result.lash example.'},
            {'topic': 'minimal proposal', 'resolution': 'Replace only Invalid((1,)) on the right side of the invalid-lash assertion by Valid(2). Retain the other Valid short-circuit assertion. One historical source unit, no transfer, one new expected relationship.'},
            {'topic': 'failure mapping', 'resolution': 'Actual direct Invalid.lash recovery and related pointfree/Fold failures agree on the no-op defect. This is assertion repair, not an absent setup or a successful historical-fragment assembly.'},
        ])
        checked = ['s8_c0', 's95_c0', 's110_c0']
        extent = 'trigger_already_executed_wrong_check_correct_rule_available_only_as_contract_source'
    else:
        d['alternative_actual_failure'] = {k: copy.deepcopy(b[k]) for k in
            ['target_operation', 'agent_base_units', 'missing_factors', 'minimal_assembly', 'oracle_availability']}
        if cid == 'S068':
            notes.extend([
                {'topic': 'different independently selected failures', 'resolution': 'A selects enable-safe-import on a missing file; B selects actual bulk UPDATE validation bypass. Preserve A as focal and B as another archived task failure. They are not competing provenance labels for the same target operation.'},
                {'topic': 'historical base', 'resolution': '77 creates Database and inserts two rows before invoking enable; the complete script reaches ALL CLI TESTS PASSED. Move that existing DB/table initialization after the original enable success assertion, before add-import-invariant. Keep the entire CLI sequence and all assertions.'},
                {'topic': 'contract strength', 'resolution': 'Archived enable fails with parser exit2 on a fresh filename, and disable then fails because enable never created it. The Issue names the CLI commands but does not explicitly state file-creation behavior. The expected creation is supported by the official test/reference workflow; treat its textual task-contract support as less explicit than the UPDATE requirement and qualify on R before claiming a valid detection.'},
                {'topic': 'alternative reuse', 'resolution': 'B transfers executed COUNT(*)<1 plus rejecting insert/rollback observations into85 bulk-update base, reached in127 full1078PASS. It requires a changed rejection/value oracle and is not a pure context repair. Predicate is false both before and after update; label this mandatory validation case separately from a valid-to-invalid transition.'},
            ])
            d['oracle_availability']['task_contract_specificity'] = 'CLI operation explicit; behavior for a nonexistent database filename implicit, with official test/reference support. Reference execution and semantic adjudication remain required.'
            checked = ['s77_c0', 's85_c0', 's127_c0']
            extent = 'fresh_path_context_absent_for_primary_other_update_failure_has_reusable_components'
        else:
            notes.extend([
                {'topic': 'different independently selected failures', 'resolution': 'A selects absent Database.safe_bulk_insert API; B selects incorrect cleanup error for a still-active checkpoint. Both occur in the archived13failures. Preserve A as focal and B as a distinct valid task-failure assembly.'},
                {'topic': 'primary actual source', 'resolution': '164 defines test_safe_bulk_insert_rolls_back_on_invariant_failure using db["t"].safe_bulk_insert;164ninePASS and198full1061PASS establish execution. Replace only that call with db.safe_bulk_insert("t",records), preserving the structured-failure and count assertions. No Database-level invocation was found in history.'},
                {'topic': 'scope correction', 'resolution': 'The original164 rollback test ends at count==1 and has no explicit cleanup call. A reference to retaining final cleanup does not describe this unit. Retain the actual full original body without inventing an extra cleanup assertion.'},
                {'topic': 'exact alternative context', 'resolution': 'Original checkpoint_commit_rollback_rules finalizes an ID before cleanup; nested_checkpoints separately creates a fresh active inner ID. B proposes assigning a new create_import_checkpoint() result immediately before the original cleanup phase. This preserves all preceding finalized-ID assertions and transfers the active state into the existing NotFound check.'},
                {'topic': 'alternative cardinality', 'resolution': 'Cleanup alternative uses2 named source units,1 exact Context transfer,0 new semantic elements. The new receiver primitive in the primary is separately counted; do not average the two missing-factor inventories into one witness.'},
            ])
            d['minimal_assembly']['absent_semantic_primitives'] = ['Invoke the task-specified Database-level method with table argument.']
            checked = ['s164_c0', 's198_c0']
            extent = 'public_API_trigger_absent_for_primary_exact_active_checkpoint_transfer_for_other_failure'
        d['any_task_failure_availability'] = {
            'additional_confirmed_failure_in_review_B': True,
            'missing_provenance_classes': [f['provenance_class'] for f in b['missing_factors']],
            'source_units': b['minimal_assembly']['distinct_historical_source_units_including_base'],
            'transferred_fragments': b['minimal_assembly']['transferred_fragments'],
            'new_semantic_elements': b['minimal_assembly']['new_semantic_elements'],
            'execution_validated': False}

    d['fragment_compatibility'] = {'status': 'source_supported_proposal',
        'factor_mappings': [{'factor_id': f['factor_id'], 'mapping': f['compatibility']}
                            for f in d['missing_factors']], 'executed_joint_compatibility': False}
    d['oracle_availability']['independent_source_receipts'] = [sources[k] for k in
        ['issue', 'verifier_test', 'reference_solution']]
    path = Path(sources['archived_verifier_stdout']['path'])
    raw = path.read_text()
    start = raw.rfind('===== FAILURES')
    d['original_failure_receipt'] = {'source': receipt(path), 'start_char': start,
                                    'excerpt': raw[start:start + 8500]}
    d['root_source_checks'] = {'action_receipts': [{k: actions[x][k] for k in
        ['id', 'step_id', 'call_index', 'tool_call_id', 'command_sha256', 'observation_content_sha256']}
        for x in checked], 'issue': sources['issue'], 'scope': 'Original definitions, completion evidence and actual Verifier errors; no candidate execution.'}
    classes = [f['provenance_class'] for f in d['missing_factors']]
    d['counts'] = {'missing_factor_count': len(classes),
        'missing_exact': classes.count('Exact Executed Fragment'),
        'missing_related': classes.count('Related Executed Components'),
        'missing_absent': classes.count('Absent'), 'missing_unresolved': classes.count(None),
        'has_missing_exact_fragment': 'Exact Executed Fragment' in classes,
        'all_missing_factors_exact': bool(classes) and all(x == 'Exact Executed Fragment' for x in classes),
        'all_missing_factors_have_executed_components': bool(classes) and all(x in
            ['Exact Executed Fragment', 'Related Executed Components'] for x in classes),
        'historical_support_extent': extent, 'complete_historical_joint_witness': False,
        'manual_execution_validated': False, 'blind_execution_validated': False}
    d['remaining_work_for_goal'] = ['Complete and freeze all88 source adjudications',
        'Execute automatic candidates and source-unit controls; distinguish focal and other actual task-failure detections']
    with (OBS / f'adjudicated/{cid}.json').open('x') as stream:
        json.dump(d, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
    print(cid, extent)
