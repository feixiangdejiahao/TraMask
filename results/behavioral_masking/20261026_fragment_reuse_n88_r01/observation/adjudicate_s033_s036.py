"""Root source adjudications; informed phase only, no candidate execution claim."""
from pathlib import Path
import copy
import hashlib
import json

OBS = Path(__file__).resolve().parent
RUN = OBS.parent


def load(p):
    return json.loads(p.read_text())


def save(p, value):
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open('x') as f:
        json.dump(value, f, ensure_ascii=False, indent=2)
        f.write('\n')


audit = {
    'scope': 'S033/S034 finite-max grid oracle; evaluator-only source audit',
    'checked_on': '2026-10-26',
    'primary_source': 'https://www.w3.org/TR/2025/CRD-css-grid-1-20250326/#algo-grow-tracks',
    'title': 'CSS Grid Layout Module Level1, sections11.4 and11.6',
    'finding': 'Fixed minima initialize base sizes and fixed maxima initialize growth limits. Positive free space grows base sizes until growth limits. Gutters participate as fixed-size tracks.',
    'inference_for_task': 'The requested CSS grid minmax feature inherits this finite-bound behavior absent a task override. With ample width, minmax(3,5) plus gap1 places the next column at6; minmax(5,10) with no gap places it at10.',
    'historical_availability': 'This root external verification is not an executed Agent fragment and is not added to blind inputs. S033 lacks a full correct finite-max historical oracle; S034 contains one.',
}
audit_path = OBS / 'oracle_audits/finite_max_grid.json'
save(audit_path, audit)

for case in ['S033', 'S034', 'S035', 'S036']:
    rs = {k: load(OBS / f'reviewer_{k}/{case}.json') for k in ['A', 'B']}
    a, b = rs['A'], rs['B']
    primary = b if case == 'S033' else a
    sources = load(OBS / f'sources/{case}.json')['sources']
    frozen = {}
    for role in ['A', 'B']:
        raw = (OBS / f'reviewer_{role}/{case}.json').read_bytes()
        dst = OBS / f'frozen_reviews/{role}/{case}.json'
        dst.parent.mkdir(parents=True, exist_ok=True)
        if dst.exists():
            assert dst.read_bytes() == raw
        else:
            dst.write_bytes(raw)
        frozen[role] = {'path': str(dst.relative_to(RUN)), 'sha256': hashlib.sha256(raw).hexdigest()}
    assembly = primary['minimal_assembly']
    d = {
        'schema_version': 'fragment-observation-adjudication.v1',
        'case_id': case, 'trial': primary['trial'], 'task': primary['task'],
        'known_case': primary.get('known_case'), 'status': 'complete',
        'adjudicator': 'Codex /root', 'reviews': frozen,
        'target_operation': copy.deepcopy(primary['target_operation']),
        'required_factor_inventory': copy.deepcopy(primary['required_factor_inventory']),
        'agent_base_units': copy.deepcopy(primary['agent_base_units']),
        'missing_factors': copy.deepcopy(primary['missing_factors']),
        'oracle_availability': copy.deepcopy(primary['oracle_availability']),
        'minimal_assembly': {
            'proposed_source_units': assembly['distinct_historical_source_units_including_base'],
            'proposed_transferred_fragments': assembly['transferred_fragments'],
            'new_semantic_elements': assembly['new_semantic_elements'],
            'source_proposals': {k: copy.deepcopy(v['minimal_assembly']) for k, v in rs.items()},
            'execution_validated_minimum': None,
        },
        'historical_joint_witness': {'complete_assertion_witness': False},
        'execution': {'status': 'not_executed_in_this_study', 'manual_assembly_success': False,
                      'blind_result': False},
        'root_source_checks': [], 'adjudication_notes': [],
        'remaining_work_for_goal': ['Finish all88 informed observations and freeze before blind generation',
                                    'Independent execution and adjudication of blind candidates'],
    }
    d['target_operation']['verifier_receipts'] = [sources[k] for k in ('verifier_test', 'archived_verifier_results')]
    d['oracle_availability']['independent_source_receipts'] = [sources[k] for k in ('issue', 'verifier_test', 'reference_solution')]
    notes = d['adjudication_notes']
    new_primitive = 0
    extent = ''

    if case == 'S033':
        new_primitive = 1
        d['oracle_availability'].update(
            available_to_blind_system=None, independently_trusted=True,
            historical_complete_oracle=False,
            external_audit='observation/oracle_audits/finite_max_grid.json',
            blind_availability_note='Issue names minmax but only explicitly states fractional-max distribution. Finite-max growth requires background semantic knowledge; the root CSS source is withheld.')
        d['missing_factors'][0]['new_semantic_primitives'] = [{
            'rule': 'With sufficient width, finite-max minmax tracks grow to their upper bound.',
            'executed_history_provenance': 'Absent',
            'independent_support': audit['primary_source'],
        }]
        d['minimal_assembly']['new_external_primitive_knowledge'] = 1
        d['root_source_checks'] = [
            {'actions': ['s77_c0', 's174_c0', 's207_c0'], 'finding': 'Fixed5/gap1 donor correctly asserts A+5spaces+B. Finite-max test first expects Bindex5 and later Bindex4; neither is the required index6.'},
            {'source': audit['primary_source'], 'finding': 'Root independently verified finite-max growth and gap accounting; this information is outside executed Agent history.'},
        ]
        notes.extend([
            {'topic': 'Check provenance disagreement', 'resolution': 'A correctly finds the missing finite-max growth rule absent. B correctly finds an actual fixed-width5/gap1 layout oracle. Root records Related for the complete Check because that task-specific layout component is reusable, and explicitly records one absent semantic primitive. Related does not mean all required knowledge existed.'},
            {'topic': 'no historical full witness', 'resolution': 'Restoring the earliest finite-max expectation would still be wrong by one column. A correct witness needs the growth rule plus the donor gap relation.'},
        ])
        extent = 'related_fixed_track_layout_component_plus_absent_finite_max_growth_rule'

    elif case == 'S034':
        d['alternative_focal_observation'] = {k: copy.deepcopy(b[k]) for k in
            ('target_operation', 'missing_factors', 'oracle_availability', 'minimal_assembly')}
        d['historical_joint_witness'] = {
            'complete_assertion_witness': False,
            'focal_behavior': 'nested flex width inheritance',
            'other_task_behavior_complete_assertion_witness': True,
            'other_behavior': 'finite-max minmax allocation',
            'complete_failed_witness_action': 's144_c0',
            'oracle_weakening_action': 's145_c0',
            'production_version': 'Same production as submitted patch; actions145–148 edit test expectation, configure Git identity, commit, and run checks without production edits.',
            'historical_outcome': 'A+4spaces+B received; A+9spaces+B expected; one actual failed Ava test.',
        }
        d['root_source_checks'] = [
            {'actions': ['s73_c0', 's114_c0', 's120_c0'], 'finding': 'Widthless fractional grid, flex-column wrapper, and successful explicit-width fractional test exist as separate executed units.'},
            {'actions': ['s144_c0', 's145_c0', 's146_c0', 's147_c0', 's148_c0'], 'finding': 'Complete finite-max witness actually fails, then only expected render is weakened. No subsequent production edit is captured; final suites pass30 tests.'},
        ]
        notes.extend([
            {'topic': 'distinct focal choices', 'resolution': 'Retain A predeclared nested-flex behavior for primary factor census. B selects a separate actual finite-max failure and finds a complete historical witness. Preserve both instead of merging their incompatible missing-factor sets.'},
            {'topic': 'historical baseline scope', 'resolution': 'There is no established full nested-flex witness, but the same trajectory already has a full witness for another task defect. Case-level recovery of any real task defect must compare against rerunning that finite-max test; it cannot be credited automatically to fragment assembly.'},
            {'topic': 'joint context', 'resolution': 'Move original width12 to a parent flex-column wrapper while retaining 1fr/2fr inputs and output. Both donor components ran; their exact width-transfer relationship did not.'},
        ])
        extent = 'related_width_inheritance_components_for_focal_bug_and_complete_witness_for_another_task_bug'

    elif case == 'S035':
        d['missing_factors'][0]['role'] = 'Trigger'
        d['missing_factors'][0]['semantic_condition'] = 'Pass the same logical target path using quoted token syntax to the session_bundle magic parser.'
        for inv in d['required_factor_inventory']:
            if not inv.get('present_in_base', True):
                inv['role'] = 'Trigger'
        d['root_source_checks'] = [
            {'actions': ['s60_c0', 's115_c0', 's138_c0', 's142_c0'], 'finding': 'Original roundtrip checks returned requested path. Actual quoted probe115 prints a literal-quoted filename and then loads the malformed returned path; successful loading does not assert intended path identity.'},
            {'source': sources['archived_verifier_results'], 'finding': 'Quoted magic status explicitly compares malformed versus intended path; related quoted ZIP tests fail to find the intended file.'},
        ]
        notes.extend([
            {'topic': 'Trigger versus Context', 'resolution': 'Both reviewers call quoting an input-representation context. Root classifies it as Trigger because the selected target includes parsing the magic argument string, and the edit changes that input syntax, not an established environment state. Provenance remains Exact.'},
            {'topic': 'fragment compatibility', 'resolution': 'Transfer quote delimiters onto the existing target interpolation; preserve original target path, return-path assertion, status and roundtrip operations. No donor basename or space is needed.'},
            {'topic': 'printed error versus full witness', 'resolution': 'Donor115 visibly produced wrong path identity but never checked it against intended input. It is a reusable executed stimulus, not a full asserted witness.'},
        ])
        extent = 'exact_quoted_argument_trigger_transfer_to_existing_path_identity_oracle'

    elif case == 'S036':
        factor = d['missing_factors'][0]
        factor['provenance_class'] = 'Related Executed Components'
        factor['source_fragments'] = copy.deepcopy(b['missing_factors'][0]['source_fragments'])
        factor['absence_evidence'] = a['missing_factors'][0]['absence_evidence']
        factor['absence_scope'] = 'Exact repeated Read after already returned terminal error; not absence of every related executed terminal/read component.'
        factor['compatibility']['related_component_mapping'] = 'Donor62 executes Read after peer stream FIN. Combine that terminal-before-Read pattern with base own-session closure and existing closed-pipe predicate. The terminal scope and repeated-call relationship are new.'
        for inv in d['required_factor_inventory']:
            if not inv.get('present_in_base', True):
                inv['history_provenance'] = 'Related Executed Components'
        d['minimal_assembly'].update(proposed_source_units=2, proposed_transferred_fragments=1,
            new_semantic_elements=1, new_external_primitive_knowledge=0,
            root_assembly='After original blocked reader returns ErrClosedPipe, call the same stream Read again and require the same task-specified error.')
        d['root_source_checks'] = [
            {'actions': ['s24_c0', 's62_c0', 's65_c0'], 'finding': 'Base validates reader already blocked during session close. Separate62 explicitly closes a peer stream then Reads EOF and passes under race test. No existing repeated-read-after-terminal-error witness is shown.'},
            {'source': sources['verifier_test'], 'finding': 'Official failing unit first validates pending reader unblocking with ErrClosedPipe, then performs second Read and fails because it returnsEOF.'},
        ]
        notes.extend([
            {'topic': 'same defect, different assemblies', 'resolution': 'A appends a second Read after terminal error; B moves first Read after session-close completion. Retain A sequence matching actual failing verifier phase and B alternative as a distinct unexecuted timing assembly.'},
            {'topic': 'provenance disagreement', 'resolution': 'Exact post-session terminal reread is absent, but B supplies an actually executed terminal-event→Read component with another close scope. Root records Related and the new temporal/scope relation, rather than treating API repetition alone as Exact.'},
            {'topic': 'oracle', 'resolution': 'Issue explicitly requires closed session operations to return ErrClosedPipe. EOF for peer half-close is a different contract and is not transferred as the expected error.'},
        ])
        extent = 'related_terminal_before_read_component_with_new_session_scope_and_repeated_read_relation'

    d['fragment_compatibility'] = {
        'status': 'source_supported_proposal', 'cross_unit_transfer_support': True,
        'factor_mappings': [{'factor_id': f['factor_id'], 'mapping': f['compatibility']} for f in d['missing_factors']],
        'executed_joint_compatibility': False,
    }
    cls = [f['provenance_class'] for f in d['missing_factors']]
    d['counts'] = {
        'missing_factor_count': len(cls), 'missing_exact': cls.count('Exact Executed Fragment'),
        'missing_related': cls.count('Related Executed Components'), 'missing_absent': cls.count('Absent'),
        'missing_unresolved': cls.count(None),
        'has_missing_exact_fragment': 'Exact Executed Fragment' in cls,
        'all_missing_factors_exact': bool(cls) and all(x == 'Exact Executed Fragment' for x in cls),
        'all_missing_factors_have_executed_components': all(x in ['Exact Executed Fragment', 'Related Executed Components'] for x in cls),
        'new_external_semantic_primitives': new_primitive,
        'history_evidence_extent': extent, 'cross_unit_transfer_support': True,
        'complete_historical_witness': False,
        'any_task_complete_historical_witness': case == 'S034',
        'manual_validated_assembly': False, 'automatic_validated_assembly': False,
    }
    save(OBS / f'adjudicated/{case}.json', d)
    print(case, d['counts'])
