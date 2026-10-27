"""Root source adjudications, kept outside the blind generation inputs."""
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


for cid in ['S021', 'S022', 'S023', 'S024']:
    reviews = {r: read(OBS / f'reviewer_{r}/{cid}.json') for r in ['A', 'B']}
    a, b = reviews['A'], reviews['B']
    sources = read(OBS / f'sources/{cid}.json')['sources']
    actions = {x['id']: x for x in read(RUN / f'public_inputs/{cid}/history.json')['actions']}
    frozen = {}
    for role in ['A', 'B']:
        src = OBS / f'reviewer_{role}/{cid}.json'
        dst = OBS / f'frozen_reviews/{role}/{cid}.json'
        dst.parent.mkdir(parents=True, exist_ok=True)
        with dst.open('xb') as stream:
            stream.write(src.read_bytes())
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
        'new_external_primitive_knowledge': 0,
        'source_proposals': {r: copy.deepcopy(x['minimal_assembly']) for r, x in reviews.items()},
        'execution_validated_minimum': None,
    }
    d['historical_joint_witness'] = {'complete_assertion_witness': False}
    d['execution'] = {'status': 'not_executed_in_this_study',
                      'manual_assembly_success': False, 'blind_result': False}
    notes = d['adjudication_notes'] = []

    if cid == 'S021':
        d['historical_joint_witness'].update(joint_target_and_correct_result_observed=True,
            observation_action='s45_c0',
            reason='Earlier mixed text-update/sibling-append probe prints conflicts0 and merged updated child plus sibling, but has no hard correctness assertion.')
        notes.extend([
            {'topic': 'stronger donor', 'resolution': 'Root inspected45: base a1,b2; ours appendsc; theirs changesa1→9; actual result has conflicts0 and both edits. This is a more specific donor than B29 same-child conflict fixture. Retain A transfer into51 existing zero-conflict assertion.'},
            {'topic': 'oracle disagreement', 'resolution': 'B reasonably derives add-versus-text independence from its selected components. Root uses the already executed exact mixed operation45 plus Issue conflict definitions and51 hard no-conflict contract. No additional Check edit is needed; earlier correct output is not promoted to a complete asserted witness.'},
            {'topic': 'scope and version', 'resolution': '51 hard-tests independent adds. Replace one branch append by45 text modification with role mapping; preserve complete selected unit and zero-conflict check.45 is an earlier implementation, not final-P execution evidence.'},
            {'topic': 'archived failure counts', 'resolution': 'Fifteen P2P missing results arise from base compilation/collection, while five F2P entries have actual runtime failures. Selected Merge3Way no-conflicts assertion is one of the executed failures; do not treat all20 rows as behavioral bugs.'},
        ])
        checked = ['s45_c0', 's51_c0']
        extent = 'exact_mixed_edit_trigger_observed_without_hard_check_then_transfer_to_independence_test'
    elif cid == 'S022':
        d['alternative_base_proposal'] = {k: copy.deepcopy(b[k]) for k in
            ['agent_base_units', 'missing_factors', 'minimal_assembly']}
        notes.extend([
            {'topic': 'actual failed observation', 'resolution': 'Verifier FinallyBodyThrows receives a caught result and compares finally boom against {finally boom}. Throw propagation succeeded; the mismatch is expression-language string conversion. Do not attribute it to omitted finally execution.'},
            {'topic': 'same missing operation', 'resolution': 'Both independent reviewers find no executed language string(caughtError) call. A uses final162 boom row; B uses earlier numeric123 row. Retain A predeclared final complete-table row edit and B alternative separately.'},
            {'topic': 'host versus language conversion', 'resolution': '162 fmt.Sprintf handles the raw caught object and passes expectedboom. Adding string(e) inside the language makes the returned value a string, whose braces are not removed by the unchanged host comparison. This requires a new Trigger, not another context donor.'},
            {'topic': 'earlier failure', 'resolution': '116 manual finally tests fail because err.Error contains source-location decoration. That observation is distinct from the final Verifier language-string wrapper mismatch and is not the selected complete historical witness.'},
        ])
        checked = ['s116_c0', 's162_c0']
        extent = 'language_conversion_trigger_absent_existing_host_comparison_can_be_retained'
    else:
        # The expected message relation is already checked on a host error, but
        # moving it to the language result is still a new observation relation.
        check = next(f for f in d['missing_factors'] if f['role'] == 'Check')
        donor = next(f for f in b['missing_factors'] if f['role'] == 'Check')
        check['provenance_class'] = 'Related Executed Components'
        check['source_fragments'] = copy.deepcopy(donor.get('source_fragments', []))
        check['component_scope'] = 'Specific message observation in the same original test; no extra source unit or external Check donor.'
        check['new_relation'] = 'Language string(caughtError) must expose the original message rather than wrapper representation.'
        for item in d['required_factor_inventory']:
            if item.get('role') == 'Check' and not item.get('present_in_base'):
                item['history_provenance'] = 'Related Executed Components'
        d['oracle_availability']['historical_check_provenance'] = 'Related Executed Components'
        d['minimal_assembly']['derived_joint_relations'] = ['Transfer the already observed host-message obligation to the newly invoked language conversion.']
        if cid == 'S023':
            notes.extend([
                {'topic': 'oracle component versus full relation', 'resolution': 'Original103 TestThrow explicitly checks numeric message42 through out.(error).Error(). A labels the complete language-result Check Absent; B identifies that specific message component as Related. Root records Related support within the same base while keeping the new language operation Absent and counting two semantic edits.'},
                {'topic': 'reached version', 'resolution': '103 fails unused-import compilation;105 repairs the file and the targeted tests pass. The original host-error cast must be removed when catch returns a language string. Copying generic require.Equal syntax alone is not additional provenance.'},
                {'topic': 'baseline compatibility', 'resolution': 'The Issue binds an error but does not require the exact Go runtime type assumed by out.(error). Original full test must be qualified on R before interpreting a repair matrix; source-only compatibility remains unresolved.'},
            ])
            checked = ['s103_c0', 's105_c0']
            extent = 'new_language_conversion_and_related_same_unit_host_message_check_with_type_control_pending'
        else:
            notes.extend([
                {'topic': 'oracle component versus full relation', 'resolution': '142 TestThrow checks caught errtypecustom, and separately uncaught err.Error containsboom. This specific message observation is Related support, already in the base. It is not a full equality check for string(caughtError), which requires new semantics.'},
                {'topic': 'edits and units', 'resolution': 'Change errtype(e)→string(e) and expectedcustom→boom in the first original TestThrow block, retaining other checks. One source unit, zero transferred fragments, two new semantic edits; do not report this as recovery from dispersed historical tests.'},
                {'topic': 'reachability and actual failure', 'resolution': '142 suite has an unrelated type-check failure; final163 targeted race suite passes. Verifier FinallyBodyThrows got{finally boom}, demonstrating propagated throw plus bad conversion, not swallowed cleanup.'},
            ])
            checked = ['s142_c0', 's163_c0']
            extent = 'new_language_conversion_and_related_same_unit_uncaught_message_component'

    d['fragment_compatibility'] = {
        'status': 'source_supported_proposal' if cid != 'S023' else 'source_proposal_original_reference_type_compatibility_unresolved',
        'factor_mappings': [{'factor_id': f['factor_id'], 'mapping': f['compatibility']}
                            for f in d['missing_factors']],
        'executed_joint_compatibility': False,
    }
    d['oracle_availability']['independent_source_receipts'] = [sources[k] for k in
        ['issue', 'verifier_test', 'reference_solution']]
    path = Path(sources['archived_verifier_stdout']['path'])
    text = path.read_text()
    start = text.rfind('===== FAILURES')
    if cid != 'S021':
        start = text.find('TestTryCatch_FinallyBodyThrows', start)
    d['original_failure_receipt'] = {'source': receipt(path), 'start_char': start,
                                    'excerpt': text[start:start + 3200]}
    d['root_source_checks'] = {
        'action_receipts': [{k: actions[x][k] for k in ['id', 'step_id', 'call_index',
            'tool_call_id', 'command_sha256', 'observation_content_sha256']} for x in checked],
        'issue': sources['issue'], 'scope': 'Primary definitions, reached versions and actual failure messages inspected; no new execution.'}
    classes = [f['provenance_class'] for f in d['missing_factors']]
    d['counts'] = {
        'missing_factor_count': len(classes), 'missing_exact': classes.count('Exact Executed Fragment'),
        'missing_related': classes.count('Related Executed Components'), 'missing_absent': classes.count('Absent'),
        'missing_unresolved': classes.count(None),
        'has_missing_exact_fragment': 'Exact Executed Fragment' in classes,
        'all_missing_factors_exact': bool(classes) and all(x == 'Exact Executed Fragment' for x in classes),
        'all_missing_factors_have_executed_components': bool(classes) and all(x in
            ['Exact Executed Fragment', 'Related Executed Components'] for x in classes),
        'historical_support_extent': extent, 'complete_historical_joint_witness': False,
        'manual_execution_validated': False, 'blind_execution_validated': False,
    }
    d['remaining_work_for_goal'] = ['Complete and freeze all88 informed adjudications',
        'Finish uniform public workspace-source inputs and generic generator before blind freeze',
        'Execute frozen automatic candidates and historical controls; source proposals do not establish detection']
    with (OBS / f'adjudicated/{cid}.json').open('x') as stream:
        json.dump(d, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
    print(cid, extent)
