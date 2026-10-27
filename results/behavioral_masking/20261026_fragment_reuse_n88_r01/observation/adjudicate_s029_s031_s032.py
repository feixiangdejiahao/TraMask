"""Root evidence decisions for agreed HTTP/schema cases; no blind results."""
from pathlib import Path
import copy
import hashlib
import json

OBS = Path(__file__).resolve().parent
RUN = OBS.parent

NOTES = {
    'S029': [
        ('agreement', 'Both reviewers find the same already-executed duplicate-name/two-path input and an explicitly wrong single-cookie expected header. Missing factor is the complete multiplicity/order Check.'),
        ('execution reachability', 'Definition50 initially fails earlier in the script. Successful final163 reaches ALL PASSED after the ordering block; do not use the first failed whole-script run as reachability proof.'),
        ('oracle independence', 'Issue separately requires deterministic send ordering and ambiguous mapping lookup conflicts. Deduplicating the outgoing header by name does not follow from mapping conflict semantics. Independent verifier explicitly requires both matching cookies.'),
        ('assembly scope', 'Replace only expected header by name=long; name=short. No historical donor carries that complete correct Check; this is a new Issue-derived assertion, not fragment-transfer evidence.'),
    ],
    'S031': [
        ('agreement', 'Both reviewers identify the malformed in-memory test and valid live-stream test as separate actual source units. The target framing/error operation already exists; streaming state and error-path cleanup Check must be combined.'),
        ('Check semantics', 'The exact is_closed observer and normal-exhaustion expectation exist, but applying closure after DecodingError is a new relation supported by the Issue. Generic copied assertion syntax alone is insufficient.'),
        ('timing', 'Retain malformed final newline so parsing fails while byte iteration is suspended. A non-newline trailing record can be parsed only after underlying iteration already closed, hiding the selected defect.'),
        ('repair category', 'Streaming setup alone leaves only an already-passing DecodingError assertion. Proposed repair also adds the lifecycle Check and is not context-only.'),
    ],
    'S032': [
        ('agreement', 'Both reviewers find include/exclude overlap in a real executed negative test and a disjoint positive end-to-end test with the required final-schema assertions.'),
        ('compatible mapping', 'Map donor overlapping b onto the existing excluded noise column. Including noise then excluding it leaves selected a,b,c and all expected metadata unchanged.'),
        ('incorrect donor oracle', 'Only overlap state transfers. The negative test wrongly treats overlap as invalid; its rejection oracle must not transfer or be reported as a historical correct full witness.'),
        ('failure scope', 'The18 official entries fail at the common fit setup. No claim is made that their later model/alias/server assertions were reached. The full original test file also contains the incompatible overlap-invalid assertion; focal E2E unit scope is explicit.'),
    ],
}
CHECKS = {
    'S029': [(['s50_c0', 's163_c0'], 'Root inspected two matching stored cookies, outgoing request, explicit name=long check, and final ALL PASSED output.')],
    'S031': [(['s57_c0', 's82_c0', 's95_c0'], 'Root inspected original invalid NDJSON bytes and raises check, valid two-chunk generator and is_closed check, and final156-test receipt.')],
    'S032': [(['s105_c0', 's167_c0'], 'Root inspected invalid-config overlap loop, E2E selected/drop/alias assertions, and final10-test completion.')],
}

for case in NOTES:
    reviews = {k: json.loads((OBS / f'reviewer_{k}/{case}.json').read_text()) for k in ['A', 'B']}
    a = reviews['A']
    sources = json.loads((OBS / f'sources/{case}.json').read_text())['sources']
    frozen = {}
    for role in reviews:
        raw = (OBS / f'reviewer_{role}/{case}.json').read_bytes()
        dst = OBS / f'frozen_reviews/{role}/{case}.json'
        dst.parent.mkdir(parents=True, exist_ok=True)
        if dst.exists():
            assert dst.read_bytes() == raw
        else:
            dst.write_bytes(raw)
        frozen[role] = {'path': str(dst.relative_to(RUN)), 'sha256': hashlib.sha256(raw).hexdigest()}
    d = {
        'schema_version': 'fragment-observation-adjudication.v1',
        'case_id': case, 'trial': a['trial'], 'task': a['task'], 'known_case': a.get('known_case'),
        'status': 'complete', 'adjudicator': 'Codex /root', 'reviews': frozen,
        **{k: copy.deepcopy(a[k]) for k in ['target_operation', 'required_factor_inventory',
                                          'agent_base_units', 'missing_factors', 'oracle_availability']},
        'minimal_assembly': {
            'proposed_source_units': a['minimal_assembly']['distinct_historical_source_units_including_base'],
            'proposed_transferred_fragments': a['minimal_assembly']['transferred_fragments'],
            'new_semantic_elements': a['minimal_assembly']['new_semantic_elements'],
            'new_external_primitive_knowledge': 0,
            'source_proposals': {k: copy.deepcopy(v['minimal_assembly']) for k, v in reviews.items()},
            'execution_validated_minimum': None,
        },
        'fragment_compatibility': {
            'status': 'source_supported_proposal', 'cross_unit_transfer_support': case != 'S029',
            'factor_mappings': [{'factor_id': f['factor_id'], 'mapping': f['compatibility']} for f in a['missing_factors']],
            'executed_joint_compatibility': False,
        },
        'historical_joint_witness': {'complete_assertion_witness': False},
        'execution': {'status': 'not_executed_in_this_study', 'manual_assembly_success': False, 'blind_result': False},
        'root_source_checks': [{'actions': actions, 'finding': finding} for actions, finding in CHECKS[case]],
        'adjudication_notes': [{'topic': topic, 'resolution': resolution} for topic, resolution in NOTES[case]],
        'remaining_work_for_goal': ['Finish all88 informed observations and freeze', 'Generate and evaluate blind candidates independently'],
    }
    d['target_operation']['verifier_receipts'] = [sources[k] for k in ['verifier_test', 'archived_verifier_results']]
    d['oracle_availability']['independent_source_receipts'] = [sources[k] for k in ['issue', 'verifier_test', 'reference_solution']]
    cls = [f['provenance_class'] for f in d['missing_factors']]
    d['counts'] = {
        'missing_factor_count': len(cls), 'missing_exact': cls.count('Exact Executed Fragment'),
        'missing_related': cls.count('Related Executed Components'), 'missing_absent': cls.count('Absent'),
        'missing_unresolved': cls.count(None), 'has_missing_exact_fragment': 'Exact Executed Fragment' in cls,
        'all_missing_factors_exact': all(x == 'Exact Executed Fragment' for x in cls),
        'all_missing_factors_have_executed_components': all(x in ['Exact Executed Fragment', 'Related Executed Components'] for x in cls),
        'history_evidence_extent': {
            'S029': 'same_full_stimulus_already_executed_but_correct_multiplicity_check_absent',
            'S031': 'exact_streaming_context_and_related_cleanup_check_components_need_error_path_composition',
            'S032': 'exact_overlap_context_transfer_from_wrong_negative_test_into_valid_positive_oracle',
        }[case],
        'cross_unit_transfer_support': case != 'S029',
        'manual_validated_assembly': False, 'automatic_validated_assembly': False,
    }
    path = OBS / f'adjudicated/{case}.json'
    with path.open('x') as f:
        json.dump(d, f, ensure_ascii=False, indent=2)
        f.write('\n')
    print(case, d['counts'])
