"""Root adjudications after independent framework/execution receipt corrections."""
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


for cid in ['S064', 'S067']:
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
    d = {k: copy.deepcopy(a[k]) for k in ['case_id', 'trial', 'task', 'known_case',
        'target_operation', 'required_factor_inventory', 'agent_base_units',
        'missing_factors', 'oracle_availability']}
    d.update(schema_version='fragment-observation-adjudication.v1', status='complete',
             adjudicator='Codex /root', reviews=frozen)
    d['minimal_assembly'] = {
        'proposed_source_units': a['minimal_assembly']['distinct_historical_source_units_including_base'],
        'proposed_transferred_fragments': a['minimal_assembly']['transferred_fragments'],
        'new_semantic_elements': a['minimal_assembly']['new_semantic_elements'],
        'new_external_primitive_knowledge': a['minimal_assembly'].get('new_external_primitive_knowledge', 0),
        'source_proposals': {r: copy.deepcopy(x['minimal_assembly']) for r, x in reviews.items()},
        'execution_validated_minimum': None,
    }
    d['alternative_B_proposal'] = {k: copy.deepcopy(b[k]) for k in
        ['target_operation', 'agent_base_units', 'missing_factors', 'minimal_assembly', 'oracle_availability']}
    d['historical_joint_witness'] = {'complete_assertion_witness': False}
    d['execution'] = {'status': 'not_executed_in_this_study',
                      'manual_assembly_success': False, 'blind_result': False}
    notes = d['adjudication_notes'] = []
    if cid == 'S064':
        notes.extend([
            {'topic': 'actual adapter', 'resolution': 'Verifier patch adds packages/preact-query/src/__tests__/fine-grained-persister.restore-state.test.tsx, imports preact/hooks and runs from preact-query. The actual two public-result failures are Preact. B independently corrected its initial React attribution and retained the earlier review.'},
            {'topic': 'what actually ran', 'resolution': '146 reports7core and4persist-client tests passing.107 executes React tests but fails at React.act is not a function before the intended mounting behavior. That harness failure supplies neither successful Preact execution nor a reusable executed adapter primitive.'},
            {'topic': 'primary assembly', 'resolution': 'A proposes applying the executed core result predicates to a real Preact mounted observer over persisted error state. Existing QueryObserver71 asserts isRefetchError and failureCount3, while fine-grained prefetch82 checks cached error state. Mounting the public Preact adapter is absent from executed history, so no all-historical compatible assembly is established.'},
            {'topic': 'alternative mechanism remains a hypothesis', 'resolution': 'B identifies default refetch options in bulk82 and noninvalidated state from71; it proposes observing fine-grained prefetch after scheduling. These are real source components, but no execution proves that combining them reproduces the two actual Preact failures. Symbol/package identity and scheduling causes remain unresolved.'},
            {'topic': 'alternative Check adaptation', 'resolution': 'Original prefetch82 explicitly asserts isInvalidated true. An alternative setting false must also adjust that corresponding expected field; it cannot literally retain every base assertion. Post-scheduling no-refetch decision is another new observation relation. A proposed source count is not an executable minimum.'},
        ])
        d['minimal_assembly']['assembly_status'] = 'new_adapter_primitive_required_joint_execution_unresolved'
        checked = ['s71_c0', 's82_c0', 's107_c0', 's146_c0']
        extent = 'preact_adapter_execution_absent_related_core_public_result_oracle_available'
    else:
        notes.extend([
            {'topic': 'actual source execution binding', 'resolution': '153 defines both CLI units and ends1failed17passed, with the failure in a different invariant CRUD test. Final248 runs the full1070passing suite.225 is only an inline API smoke; B independently corrected all source execution receipts to248 before this freeze.'},
            {'topic': 'primary valid-to-invalid transition', 'resolution': 'Retain A name-predicate proposal: original bulk UPDATE changes One to OneUpdated; combine existing rowwise id<10 validation pattern with new name!=OneUpdated predicate, plus CLI rejection and before-value preservation. New field predicate and update rollback relation are explicitly counted.'},
            {'topic': 'exact alternative', 'resolution': 'B can instead transfer exact COUNT(*)=2 from the insert test into the one-row UPDATE base, with enable/persistence setup. This predicate is already false before UPDATE, so it probes mandatory post-write validation without reproducing the Verifier valid-to-invalid state transition. Preserve it as an alternative, not as the same Context provenance.'},
            {'topic': 'oracle and mutation scope', 'resolution': 'Issue explicitly requires validation after safe writes, rollback on failure and nonzero CLI exit for an uncommitted operation, including UPDATE. The original success and updated-name assertions must change to rejection and original-name checks; this is not context-only repair.'},
        ])
        d['alternative_B_proposal']['root_scope'] = 'Same validation-bypass defect, but initially-invalid table state rather than a valid-to-invalid update; P/R behavior not yet executed.'
        checked = ['s153_c0', 's248_c0']
        extent = 'related_row_predicate_and_reject_rollback_components_require_new_update_relation'

    d['fragment_compatibility'] = {'status': 'new_adapter_execution_unresolved' if cid == 'S064' else 'source_supported_proposal',
        'factor_mappings': [{'factor_id': f['factor_id'], 'mapping': f['compatibility']}
                            for f in d['missing_factors']], 'executed_joint_compatibility': False}
    d['oracle_availability']['independent_source_receipts'] = [sources[k] for k in
        ['issue', 'verifier_test', 'reference_solution']]
    path = Path(sources['archived_verifier_stdout']['path'])
    raw = path.read_text()
    start = raw.rfind('===== FAILURES')
    d['original_failure_receipt'] = {'source': receipt(path), 'start_char': start,
                                    'excerpt': raw[start:start + 6500]}
    d['root_source_checks'] = {'action_receipts': [{k: actions[x][k] for k in
        ['id', 'step_id', 'call_index', 'tool_call_id', 'command_sha256', 'observation_content_sha256']}
        for x in checked], 'issue': sources['issue'], 'scope': 'Original source, actual run identity, framework and archived failure assertions; no new execution.'}
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
    d['remaining_work_for_goal'] = ['Complete and freeze all88 source observations',
        'Execute independently frozen blind candidates and historical controls; adjudicate actual failure cause from execution']
    with (OBS / f'adjudicated/{cid}.json').open('x') as stream:
        json.dump(d, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
    print(cid, extent)
