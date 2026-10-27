"""Root informed source adjudications; never a blind generator input."""
from pathlib import Path
import copy
import hashlib
import json

OBS = Path(__file__).resolve().parent
RUN = OBS.parent


def read(path):
    return json.loads(path.read_text())


def receipt(path):
    data = path.read_bytes()
    return {'path': str(path), 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}


for cid in ['S057', 'S061', 'S062', 'S063']:
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
    # B supplies the primary assembly for these four cases, with root corrections
    # below; A's independently selected alternatives remain separately available.
    d = {k: copy.deepcopy(b[k]) for k in ['case_id', 'trial', 'task', 'known_case',
        'target_operation', 'required_factor_inventory', 'agent_base_units',
        'missing_factors', 'oracle_availability']}
    d.update(schema_version='fragment-observation-adjudication.v1', status='complete',
             adjudicator='Codex /root', reviews=frozen)
    d['alternative_A_proposal'] = {k: copy.deepcopy(a[k]) for k in
        ['agent_base_units', 'missing_factors', 'minimal_assembly', 'oracle_availability']}
    d['minimal_assembly'] = {
        'proposed_source_units': b['minimal_assembly']['distinct_historical_source_units_including_base'],
        'proposed_transferred_fragments': b['minimal_assembly']['transferred_fragments'],
        'new_semantic_elements': b['minimal_assembly']['new_semantic_elements'],
        'new_external_primitive_knowledge': 0,
        'source_proposals': copy.deepcopy({r: x['minimal_assembly'] for r, x in reviews.items()}),
        'execution_validated_minimum': None,
    }
    d['historical_joint_witness'] = {'complete_assertion_witness': False}
    d['execution'] = {'status': 'not_executed_in_this_study',
                      'manual_assembly_success': False, 'blind_result': False}
    notes = d['adjudication_notes'] = []

    if cid == 'S057':
        notes.extend([
            {'topic': 'actual historical components', 'resolution': '71 prints stock .n/.i selector and group-class binding. The unchanged stock unit and new child-selector unit both execute in330→331 final65PASS.71 is source visibility,331 is completion evidence;72 snapshot filenames alone do not establish stock expected-output bytes.'},
            {'topic': 'Check disagreement', 'resolution': 'A correctly notes no complete class-ownership oracle in historical stock snapshots. B identifies the specific existing g/path retention relation in265/268, not merely snapshot syntax. Root records this partial Check as Related, with new class-on-anchor obligation explicitly derived from the Issue.'},
            {'topic': 'primary class and alternative id', 'resolution': 'Use B class-qualified primary to match the actual additional stock component. Keep original id only as an unrelated attribute whose placement needs independent R qualification; class n must stay on g. A older #a alternative requires id-on-g, but that id ownership is not silently imposed on the class-qualified assembly.'},
            {'topic': 'scope of composition', 'resolution': 'One additional stock source unit supplies class binding; the Check component is already in the base. Two source units, one transferred fragment, two new joint relations. This is not an entirely historical oracle.'},
        ])
        d['minimal_assembly']['derived_joint_relations'] = [
            'Combine flat class binding with the existing structural child-selector anchor.',
            'Extend existing group/path retention to preservation of the newly anchoring class.']
        d['oracle_availability']['historically_absent_full_relation'] = 'Class qualifier must remain on its ancestor anchor; derive from task selector-preservation contract.'
        checked = ['s71_c0', 's265_c0', 's268_c0', 's330_c0', 's331_c0']
        extent = 'related_class_binding_and_base_group_retention_with_new_anchor_ownership_relation'
    elif cid == 'S061':
        for item in d['missing_factors'] + d['required_factor_inventory']:
            if item.get('factor_id') == 'F2':
                item['role'] = 'Trigger'
                item['root_role_basis'] = 'The IP is a second comparator input, not environmental state.'
        notes.extend([
            {'topic': 'partial Trigger disagreement', 'resolution': 'A finds no complete leading-zero malformed version. B identifies actual valid v-prefixed versions45 plus actual leading-zero string chunks118. Under the declared Related definition these are specific input components, while the rule that leading-zero core versions are invalid remains absent from executed history.'},
            {'topic': 'independent rule', 'resolution': 'Issue requires invalid semantic versions to fall back. Root independently checked SemVer2.0.0 section2, which excludes leading zeroes in major/minor/patch. Therefore v1.02.3 is untyped and sorts after the existing IP. This external audit is evaluator-only; it is not injected into the blind input.'},
            {'topic': 'input role', 'resolution': 'Both changed comparator operands are Trigger changes. Retain the malformed-row positive-sign assertion. Calling the comparison partner Context would obscure that this is a changed stimulus, not setup repair.'},
            {'topic': 'source cardinality', 'resolution': 'Count named table subtests separately when one is the selected base: invalid-semver row, valid-v-prefix row and IPv4 row, plus the separate leading-zero test, total4. These occupy2 parent Go test functions. B grouped two donor rows under one unit; both granularities are now explicit.'},
            {'topic': 'smaller alternative', 'resolution': 'A can derive the new malformed lexeme without transferring the leading-zero and v-prefix rows: base plus IP row,2 source subtests,1 transferred input,1 new semantic input. Preserve this distinct source-minimal proposal; do not call the missing invalidity rule an observed historical oracle.'},
            {'topic': 'incorrect historical check', 'resolution': '118 tests leading-zero natural-string tie behavior and includes a shorter-first oracle. Only its input representation is reused. That check does not establish semver invalidity or justify transferring its expectation.'},
        ])
        d['minimal_assembly'].update(proposed_source_units=4, proposed_transferred_fragments=3,
            parent_test_functions=2, new_external_primitive_knowledge=1,
            absent_semantic_primitives=['Leading zeroes invalidate the numeric core of a semantic version.'],
            source_minimal_alternative={'review': 'A', 'source_units': 2, 'transferred_fragments': 1,
                'new_semantic_elements': 1, 'execution_validated_minimum': None})
        d['oracle_availability']['external_primary_source'] = {
            'url': 'https://semver.org/spec/v2.0.0.html', 'section': '2',
            'checked_by': 'Codex /root via web open',
            'paraphrase': 'The three numeric components of a normal semantic version cannot have leading zeroes.',
            'scope': 'Independent informed oracle audit only; not supplied to the blind generator.',
            'historical_rule_execution_found': False}
        d['oracle_availability']['available_to_blind_system'] = None
        d['oracle_availability']['blind_availability_basis'] = 'Issue names semantic-version validity but does not spell out the no-leading-zero rule. Whether frozen workspace contains that rule has not been established.'
        checked = ['s45_c0', 's118_c0', 's156_c0']
        extent = 'related_lexical_components_and_exact_IP_input_but_semver_invalidity_rule_not_historical'
    elif cid == 'S062':
        notes.extend([
            {'topic': 'stronger existing combination', 'resolution': 'A proposes new ID65535. B supplies actual ID7 from final smoke and actual capacity2 from the earlier capacity unit. Root selects B because it targets the same ID-versus-count defect using existing values and an existing hard-asserting base.'},
            {'topic': 'executed versions', 'resolution': '106 fails peer-send after close.108 adds explicit propagation wait and reruns to FINAL SMOKE TEST PASSED; retain that version.30 prints capacity ValueError OK before a different later FAIL; this proves the donor capacity path, not a semantically passing whole script.'},
            {'topic': 'one semantic condition', 'resolution': 'Replace the two peer max_channels64 constructor arguments by2. Their shared count-capacity condition is one factor even though there are two textual edits. ID7, existing stats, I/O, close waits, and reopening checks remain unchanged.'},
            {'topic': 'uncertain execution', 'resolution': 'The archived final patch rejects65535 above256; its same magnitude-versus-capacity check motivates7 above2. No new P/R execution has yet verified the assembled complete smoke on both implementations.'},
        ])
        checked = ['s30_c0', 's106_c0', 's108_c0']
        extent = 'exact_low_capacity_transfer_to_existing_sparse_id_hard_assertion_test'
    else:
        notes.extend([
            {'topic': 'two legitimate bases', 'resolution': 'A selects executed94 high-ID print probe and transfers default capacity; B selects executed55 assertion-bearing concurrent test and transfers ID65535. They target the same sole archived failure. Root uses B for the primary hard-check assembly and preserves A as an observational setup-only alternative.'},
            {'topic': 'do not combine labels across proposals', 'resolution': 'A is one Context change on both constructors but retains print-only ID/data observations; unguarded successful open is itself a behavioral obligation. B is one Trigger transfer, retaining existing byte/frame equality assertions. It is not valid to attribute both context-only and hard-assertion status to one synthesized base.'},
            {'topic': 'specific assertion scope', 'resolution': '55 accumulates and prints payload-prefix errors; those errors are not asserted empty. Its byte/frame equalities are hard assertions. Replacing only the first explicit ID with65535 preserves loop-index payload matching, remaining IDs2..8 and count8 below default256.'},
            {'topic': 'historical joint', 'resolution': '94 runs65535 only with max_channels65535;55 uses IDs1..8 at default256. No complete successful ID-above-capacity witness is established. Two source units and one exact input fragment suffice for the proposed new relation, with no new input constant or oracle.'},
        ])
        checked = ['s48_c0', 's55_c0', 's94_c0']
        extent = 'exact_high_id_trigger_transfer_into_default_capacity_assertion_test'

    d['fragment_compatibility'] = {'status': 'source_supported_proposal',
        'factor_mappings': [{'factor_id': f['factor_id'], 'mapping': f['compatibility']}
                            for f in d['missing_factors']], 'executed_joint_compatibility': False}
    d['oracle_availability']['independent_source_receipts'] = [sources[k] for k in
        ['issue', 'verifier_test', 'reference_solution']]
    path = Path(sources['archived_verifier_stdout']['path'])
    content = path.read_text()
    start = content.rfind('===== FAILURES')
    d['original_failure_receipt'] = {'source': receipt(path), 'start_char': start,
                                    'excerpt': content[start:start + 5500]}
    d['root_source_checks'] = {'action_receipts': [{k: actions[x][k] for k in
        ['id', 'step_id', 'call_index', 'tool_call_id', 'command_sha256', 'observation_content_sha256']}
        for x in checked], 'issue': sources['issue'],
        'scope': 'Original definitions, actual reached versions, outputs and archived failure messages; no new candidate execution.'}
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
    d['remaining_work_for_goal'] = ['Complete and freeze all88 informed adjudications',
        'Execute frozen blind candidates and historical controls; proposed source compatibility is not a detection result']
    with (OBS / f'adjudicated/{cid}.json').open('x') as stream:
        json.dump(d, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
    print(cid, extent)
