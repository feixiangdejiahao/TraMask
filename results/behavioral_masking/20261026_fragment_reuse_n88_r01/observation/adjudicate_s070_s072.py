"""Root manual adjudications of three distinct SuperJSON misses."""
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


for cid in ['S070', 'S071', 'S072']:
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
        'new_external_primitive_knowledge': 0,
        'source_proposals': {r: copy.deepcopy(x['minimal_assembly']) for r, x in reviews.items()},
        'execution_validated_minimum': None,
    }
    d['historical_joint_witness'] = {'complete_assertion_witness': False}
    d['execution'] = {'status': 'not_executed_in_this_study',
                      'manual_assembly_success': False, 'blind_result': False}
    notes = d['adjudication_notes'] = []
    if cid == 'S070':
        notes.extend([
            {'topic': 'relative missing factor', 'resolution': 'The base already grants stackFrames. Missing additional permission is exactly allowErrorProps(stack), executed in the string-mode unit. B labels the complete co-granted state Related; root counts only the missing permission relative to the base as Exact, while retaining the new frame-mode applicability relation separately.'},
            {'topic': 'stronger Check donor', 'resolution': 'A uses39 processor-can-remove-stack, rerun successfully43, which asserts absence on res.json.stack directly. This is a more appropriate observed object than B off-mode parsed.stack donor. The original frames base observes roundtripped stackFrames; a native Error stack after deserialization is not the plain serialized output.'},
            {'topic': 'new semantic check', 'resolution': 'Retain original frame roundtrip assertions, save the same serialized plain object, and apply a raw stack absence check before deserialization. Applying removal/exclusion to frames mode is a new task-derived relation, so Check remains Related rather than Exact.'},
            {'topic': 'execution correction', 'resolution': '53 reports1failed111passed, not an entirely passing suite as B narrative says; the visible failure is unrelated sanitizer expectation. Final77 explicitly reports112PASS.39 initially has2other failures,43 reruns all18PASS, including the plain-output donor. No shell rc alone is used as proof.'},
        ])
        checked = ['s39_c0', 's43_c0', 's53_c0', 's77_c0']
        extent = 'exact_permission_transfer_plus_related_plain_output_exclusion_oracle'
    elif cid == 'S071':
        notes.extend([
            {'topic': 'independent agreement', 'resolution': 'Both select the existing processor counter unit52 and default constructor from29 legacy behavior unit.52 runs126PASS;67 final suite runs131PASS. Replacing the configured constructor by new SuperJSON() transfers one exact Context condition from another executed test.'},
            {'topic': 'what must be preserved', 'resolution': 'Original unit includes outer Error with inner Error cause, allowErrorProps(stack), registered counter callback and calls==1. Preserve all of it; do not silently drop the cause to match the simpler official boolean hook test.'},
            {'topic': 'reference compatibility remains open', 'resolution': 'Default legacy cause handling can serialize the nested Error differently from configured includeCauses deep. The Issue establishes that hooks run, but the complete original calls==1 assertion under omitted options requires independent R execution. B source compatibility does not establish the correct full-unit count.'},
        ])
        checked = ['s29_c0', 's52_c0', 's67_c0']
        extent = 'exact_default_constructor_transfer_with_complete_cause_counter_reference_control_pending'
    else:
        notes.extend([
            {'topic': 'independent agreement', 'resolution': 'Both identify executed direct two-level base and separate executed deep three-Error chain in35, retained through69 final133PASS. Transfer nested Error setup while retaining outer/inner messages and direct option; do not import the donor deep-mode option.'},
            {'topic': 'partial oracle', 'resolution': 'Donor observes out.cause.cause.cause undefined after two retained Error causes. Its final input is non-Error, so that result is compatible with non-Error dropping and does not independently establish a depth cutoff for another Error. It still supplies a specific cause-boundary observation component.'},
            {'topic': 'new direct boundary', 'resolution': 'The Issue explicitly says direct keeps only the immediate cause. Derive out.cause.cause undefined for the new deeper Error, and keep the original immediate-type/message assertions. This is a new expected relation, not variable renaming or an unchanged assertion.'},
            {'topic': 'actual failure', 'resolution': 'The sole archived failure receives Error level3 at out.cause.cause.35 has3unrelated initial failures;69 runs the complete suite successfully. Two source units,2 transferred ingredients and1 new cutoff relation remain proposed until P/R execution.'},
        ])
        checked = ['s35_c0', 's69_c0']
        extent = 'exact_nested_cause_context_plus_related_boundary_observation_new_direct_depth_rule'
    d['fragment_compatibility'] = {
        'status': 'original_reference_counter_semantics_unresolved' if cid == 'S071' else 'source_supported_proposal',
        'factor_mappings': [{'factor_id': f['factor_id'], 'mapping': f['compatibility']}
                            for f in d['missing_factors']], 'executed_joint_compatibility': False}
    d['oracle_availability']['independent_source_receipts'] = [sources[k] for k in
        ['issue', 'verifier_test', 'reference_solution']]
    path = Path(sources['archived_verifier_stdout']['path'])
    raw = path.read_text()
    start = raw.rfind('===== FAILURES')
    d['original_failure_receipt'] = {'source': receipt(path), 'start_char': start,
                                    'excerpt': raw[start:start + 5500]}
    d['root_source_checks'] = {'action_receipts': [{k: actions[x][k] for k in
        ['id', 'step_id', 'call_index', 'tool_call_id', 'command_sha256', 'observation_content_sha256']}
        for x in checked], 'issue': sources['issue'], 'scope': 'Primary definitions, actual run summaries and failure assertions; no new P/R execution.'}
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
    d['remaining_work_for_goal'] = ['Complete all88 source adjudications and freeze',
        'Execute frozen blind candidates plus original controls, preserving unresolved full-unit R compatibility']
    with (OBS / f'adjudicated/{cid}.json').open('x') as stream:
        json.dump(d, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
    print(cid, extent)
