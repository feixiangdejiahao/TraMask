"""Root's informed adjudications. These records never enter the blind generator."""
from pathlib import Path
import copy
import hashlib
import json

OBS = Path(__file__).resolve().parent
RUN = OBS.parent


def read(path):
    return json.loads(path.read_text())


def write(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x') as stream:
        json.dump(obj, stream, ensure_ascii=False, indent=2)
        stream.write('\n')


def sha(data):
    return hashlib.sha256(data).hexdigest()


def action_receipt(action):
    result = {k: action[k] for k in ('id', 'step_id', 'call_index', 'tool_call_id',
                                     'command_sha256')}
    result['observation_sha256'] = action['observation_content_sha256']
    return result


def source_span(actions, definition, execution, text, fragment_id, unit_id, meaning):
    source = actions[definition]
    assert text in source['command']
    start = source['command'].index(text)
    reached = actions[execution]
    return {
        'fragment_id': fragment_id, 'source_unit_id': unit_id,
        'statement_or_condition': meaning, 'code': text,
        'code_sha256': sha(text.encode()),
        'code_span': {'kind': 'exact_command_span', 'command_action': definition,
                      'start_char': start, 'end_char': start + len(text)},
        'step_id': reached['step_id'], 'call_index': reached['call_index'],
        'tool_call_id': reached['tool_call_id'],
        'command_sha256': reached['command_sha256'],
        'observation_sha256': reached['observation_content_sha256'],
        'definition_receipt': action_receipt(source),
        'execution_receipt': action_receipt(reached),
    }


for case in ['S037', 'S038', 'S039', 'S040', 'S041', 'S042']:
    reviews = {role: read(OBS / f'reviewer_{role}/{case}.json') for role in ['A', 'B']}
    a, b = reviews['A'], reviews['B']
    sources = read(OBS / f'sources/{case}.json')
    actions = {x['id']: x for x in read(RUN / f'public_inputs/{case}/history.json')['actions']}
    frozen = {}
    for role in ['A', 'B']:
        src = OBS / f'reviewer_{role}/{case}.json'
        dest = OBS / f'frozen_reviews/{role}/{case}.json'
        dest.parent.mkdir(parents=True, exist_ok=True)
        raw = src.read_bytes()
        if dest.exists():
            assert dest.read_bytes() == raw
        else:
            dest.write_bytes(raw)
        frozen[role] = {'path': str(dest.relative_to(RUN)), 'sha256': sha(raw)}

    d = {
        'schema_version': 'fragment-observation-adjudication.v1',
        'case_id': case, 'trial': a['trial'], 'task': a['task'],
        'known_case': a.get('known_case'), 'status': 'complete',
        'adjudicator': 'Codex /root', 'reviews': frozen,
        'target_operation': copy.deepcopy(a['target_operation']),
        'required_factor_inventory': copy.deepcopy(a['required_factor_inventory']),
        'agent_base_units': copy.deepcopy(a['agent_base_units']),
        'missing_factors': copy.deepcopy(a['missing_factors']),
        'oracle_availability': copy.deepcopy(a['oracle_availability']),
        'minimal_assembly': {
            'proposed_source_units': a['minimal_assembly']['distinct_historical_source_units_including_base'],
            'proposed_transferred_fragments': a['minimal_assembly']['transferred_fragments'],
            'new_semantic_elements': a['minimal_assembly']['new_semantic_elements'],
            'source_proposals': {role: copy.deepcopy(r['minimal_assembly']) for role, r in reviews.items()},
            'execution_validated_minimum': None,
        },
        'historical_joint_witness': {'complete_assertion_witness': False},
        'execution': {'status': 'not_executed_in_this_study', 'manual_assembly_success': False,
                      'blind_result': False},
        'root_source_checks': [], 'adjudication_notes': [],
        'remaining_work_for_goal': [
            'Finish all88 informed observations and freeze before blind generation',
            'Run automatically selected candidates and historical-unit controls independently',
        ],
    }
    d['target_operation']['verifier_receipts'] = [sources['sources'][key] for key in
        ('verifier_test', 'archived_verifier_results')]
    d['oracle_availability']['independent_source_receipts'] = [sources['sources'][key] for key in
        ('issue', 'verifier_test', 'reference_solution')]
    notes = d['adjudication_notes']
    extent = ''

    if case == 'S037':
        d['historical_joint_witness'] = {
            'complete_assertion_witness': True,
            'history_category': 'complete_failed_witness_later_oracle_weakened',
            'definition_and_execution': action_receipt(actions['s54_c0']),
            'weakening': action_receipt(actions['s63_c0']),
            'original_failure': 'hasEvals expected1 received2 after setIndex(1,99)',
            'later_change': 'Same actions and state; expected evaluation counts1/2 changed to2/3.',
            'production_version': 'Earlier historical implementation; final Verifier independently reproduces the same extra evaluation. Restored unit has not yet been run on final P/R in this study.',
        }
        d['minimal_assembly']['logical_test_functions'] = 1
        d['minimal_assembly']['source_versions'] = 2
        d['minimal_assembly']['method_category'] = 'historical_oracle_restore_or_full_unit_rerun'
        d['root_source_checks'] = [
            {'actions': ['s54_c0', 's63_c0'], 'finding': 'Root inspected original asserted failure and exact expected-count substitution. Shell pipeline rc0 does not erase the explicit Jest failure.'},
            {'source': sources['sources']['issue'], 'finding': 'Collection dependencies must reflect only elements actually checked; unrelated state must not re-evaluate.'},
        ]
        notes.extend([
            {'topic': 'agreement', 'resolution': 'Both reviewers independently locate the same complete correct historical failure and later oracle weakening.'},
            {'topic': 'source-unit count', 'resolution': 'Two historical execution/version units belong to one logical named test. Restoring its previous oracle is not evidence of previously fragmented ingredients.'},
            {'topic': 'baseline', 'resolution': 'Historical full-witness rerun must be evaluated alongside automatic assemblies. This case cannot support incremental fragment-combination benefit merely by rediscovering step54.'},
        ])
        extent = 'all_missing_check_exact_but_complete_witness_already_executed'

    elif case == 'S038':
        disabled = copy.deepcopy(a['missing_factors'][0]['source_fragments'][0])
        enabled = source_span(actions, 's46_c0', 's46_c0',
            'resetContext({ atomicSelectors: true, createStore: true })',
            'S038.enabled_context', 'S038.enabled_health46',
            'Enabled reset precedes wrapper construction and successful health observation in the actual named test.')
        enabled['execution_reachability'] = 'selectorHealth exposes dependencies, dependents and dirtyCause passes in all3 tests'
        f = {
            'factor_id': 'F1', 'inventory_ref': 'C', 'role': 'Context',
            'semantic_condition': 'Retain one wrapper constructed under disabled context, then reset to enabled context before mounting it.',
            'necessity_basis': 'required_by_selected_witness',
            'provenance_class': 'Related Executed Components', 'audit_status': 'complete',
            'source_fragments': [disabled, enabled],
            'compatibility': {
                'status': 'source_supported_proposal',
                'mapping': 'In original empty-logic health unit122, reset disabled before const logic=kea({}); reset enabled after that declaration and before unchanged mount and health checks.',
                'preserved_semantics': 'Current enabled mount exposes the same health API and empty metadata; no selector/input/oracle replacement.',
                'new_relation': 'The same object crosses a context reset. The historical tests execute both regimes on different wrappers.',
                'execution_support': None,
            },
        }
        d['missing_factors'] = [f]
        d['required_factor_inventory'] = [copy.deepcopy(a['required_factor_inventory'][0]),
            {'inventory_id': 'C', 'role': 'Context', 'semantic_condition': f['semantic_condition'],
             'present_in_base': False, 'history_provenance': f['provenance_class'], 'missing_factor_id': 'F1'},
            copy.deepcopy(a['required_factor_inventory'][-1])]
        d['minimal_assembly'].update(proposed_source_units=2, proposed_transferred_fragments=1,
            new_semantic_elements=1, semantic_setup_condition_count=1, setup_statement_edits=2,
            new_external_primitive_knowledge=0,
            derived_joint_relations=['Disabled creation and enabled mount share one retained wrapper.'])
        d['root_source_checks'] = [
            {'actions': ['s46_c0', 's121_c0', 's122_c0'], 'finding': 'Separate disabled construction and enabled health tests both actually run. Final empty-logic unit122 retains function and empty-health assertions.'},
        ]
        notes.extend([
            {'topic': 'provenance granularity', 'resolution': 'Both reviews label the exact cross-reset identity/order relation Absent. Root assigns Related Executed Components to the missing context factor: its specific disabled-creation and enabled-mount components were actually executed, while their joint identity/order is new. This follows the user definition of Related; it does not make the unexecuted relation Exact.'},
            {'topic': 'factor granularity', 'resolution': 'Disabled creation plus later activation form one lifecycle context condition, implemented with two setup statements. A separately counts creation and retention; both source records remain frozen.'},
            {'topic': 'base selection', 'resolution': 'A chooses the empty-logic health unit and B chooses the dependency-rich health unit. Both exercise missing function availability; retain A complete empty unit as primary and B richer proposal as alternative.'},
        ])
        extent = 'specific_context_components_executed_but_same_object_cross_context_order_new'

    elif case == 'S039':
        d['fragment_compatibility'] = {
            'status': 'source_supported_behavioral_alignment_reference_adapter_unresolved',
            'cross_unit_transfer_support': True,
            'mapping': 'Remove only explicit field DeepMerge override in historical outer MergePolicies test, preserving policy inputs and union/origin checks.',
            'same_defect_basis': 'Issue clause7 requires unconditional union. Agent mergeConsistentHash gates union through IsMergeable/deep strategy. Historical policy source12 maps default to AugmentedShallow and refuses a second nonnil field; Reference mergeConsistentHash unions both fields without consulting strategy. Official merge-target/scalar fixtures attach both policies without a DeepMerge override.',
            'reference_compatibility': 'Reference uses consistentHashIR.policies/disabled whereas Agent test constructs headers/cookies fields and helper names. Original source test is not yet a portable identical P/R witness; a public-behavior adapter or independently justified correct implementation is needed.',
            'executed_joint_compatibility': False,
        }
        d['root_source_checks'] = [
            {'actions': ['s12_c0', 's73_c0', 's113_c0', 's115_c0', 's117_c0', 's119_c0', 's154_c0', 's155_c0'], 'finding': 'Default strategy and lower-level shallow donor are visible. Test5 initially failed compilation; test6 completes119 and final full package154→155 passes. Only actual completed test versions count.'},
            {'source': sources['sources']['patch'], 'finding': 'mergeConsistentHash returns when IsMergeable rejects two nonnil fields under AugmentedShallow; explicit DeepMerge enables union.'},
            {'source': sources['sources']['reference_solution'], 'finding': 'Reference mergeConsistentHash unconditionally unions existing policies, ignores field merge settings and uses a different private IR representation.'},
            {'source': sources['sources']['verifier_test'], 'finding': 'merge-target-route-policy and merge-target-broad-policy have targetRefs and consistentHash values but no merge annotation; same for scalar-route fixtures.'},
        ]
        notes.extend([
            {'topic': 'different operation boundaries', 'resolution': 'B retains full gateway attachment/translation and marks its missing context Absent plus unresolved trigger. A localizes the common merge operation. Root adopts the merge-operation boundary because Issue, default-strategy source, Agent guard and Reference unconditional union establish a concrete shared mechanism. Full-route integration components are not thereby claimed historically executed.'},
            {'topic': 'historical context', 'resolution': 'The effective shallow strategy is an executed donor. Translating it to an empty settings string on the outer MergePolicies call is a new relation, so Related remains appropriate.'},
            {'topic': 'portable execution', 'resolution': 'Private IR differences make original Agent test incompatible with Reference. Source-level alignment does not establish a usable P/R assembly or a detection; keep execution compatibility unresolved.'},
        ])
        extent = 'related_default_strategy_component_with_source_localized_bug_but_reference_test_portability_unresolved'

    elif case == 'S040':
        d['root_source_checks'] = [
            {'actions': ['s25_c0', 's53_c0'], 'finding': 'Visible stock singleton test defines trait({last:0,delta:0}), observes both default fields and asserts0. Actual world.test.ts executes10 passing tests; definition is before the disclosed output elision.'},
            {'actions': ['s194_c0', 's195_c0'], 'finding': 'Late probe confirms no-params default branch; selected adds/removes validation uses explicit value5 and reads before flush. No pending partial-param default assertion is established.'},
        ]
        notes.extend([
            {'topic': 'different donors', 'resolution': 'A finds an actually executed stock two-field schema and default checks. B uses authored one-field default probe and proposes empty explicit params. Keep A schema/default-check transfer as primary; B alternative is retained without claiming its expected0 was already a full partial-param oracle.'},
            {'topic': 'Check relation', 'resolution': 'The default0 rule exists in a materialized singleton. Applying it to a pending partial entity initialization requires the Issue equivalence between get before and after flush; the complete joint Check is Related.'},
            {'topic': 'context-only boundary', 'resolution': 'Adding an omitted field without observing it would leave the original value5 test blind. Proposed repair includes a second-field check and is not context-only.'},
        ])
        extent = 'exact_multifield_schema_and_related_default_check_transfer_to_pending_partial_add'

    elif case == 'S041':
        command = actions['s53_c0']['command']
        start = command.index("    it('should fully replace world state and recreate entity IDs'")
        end = command.index("    it('should throw for unknown registry keys'", start)
        donor = source_span(actions, 's53_c0', 's74_c0', command[start:end],
            'S041.rollback_equal_copies', 'rollback74',
            'Executed rollback unit creates checkpoint, restores world, independently snapshots again and asserts complete equality including Position{x:1,y:2}.')
        donor['execution_reachability'] = '37 snapshot tests pass at74, including unchanged rollbackWorld unit defined53'
        d['missing_factors'][0]['source_fragments'] = [donor]
        d['root_source_checks'] = [
            {'actions': ['s53_c0', 's74_c0'], 'finding': 'Definition53 initially collects zero tests; later corrected suite74 executes37. Rollback donor snapshots before and after separately and asserts equality. Delivered snapshot code deep-clones each data trait, establishing distinct object instances.'},
            {'source': sources['sources']['patch'], 'finding': 'snapshotEntity calls deepClone(getTrait(...)); deepClone uses structuredClone or recursive copies. Equality of the rollback snapshots is not accidental shared-object identity.'},
        ]
        notes.extend([
            {'topic': 'provenance disagreement', 'resolution': 'B only uses entity-diff donor with values1 versus2 and therefore derives equal-object context as Related. A identifies stronger rollback donor with two already flat-equal separately allocated snapshots. Root inspected the complete donor plus deep-copy implementation and retains Exact for this context.'},
            {'topic': 'target mapping', 'resolution': 'Copy flat primitive Position data into both original a:true fixture positions with separate allocations. Keep existing no-change world-diff assertion and empty-vs-missing relation setup. Nested object deep equality is outside the task shallow-equality contract.'},
        ])
        extent = 'exact_equal_independent_data_objects_transfer_to_existing_world_diff_oracle'

    elif case == 'S042':
        d['root_source_checks'] = [
            {'actions': ['s46_c0', 's77_c0', 's83_c0', 's154_c0'], 'finding': 'Early factory before two initial pairs was executed in old failed test; later passing unit83 places factory after initial additions and includes a baseline empty query. Final154 runs29 authored tests.'},
            {'source': sources['sources']['verifier_test'], 'finding': 'Selected non-last-removal test uses a long-lived factory, adds two pairs, queries empty baseline, removes one pair and expects entity. Archived result explicitly fails that expectation.'},
        ]
        d['target_operation']['focal_failure_selection'] = 'Retain A predeclared actual non-last-removal failure; B independently selected another actual AND-event failure. Neither is claimed to be the first failure in archived output.'
        notes.extend([
            {'topic': 'different focal failures', 'resolution': 'A selects non-last Removed behavior; B selects conjunctive pair Added plus relation Added. Both correspond to archived failures. Primary census uses A predeclared removal witness; retain B target/factors/assembly as a separate unexecuted alternative rather than adding its factors to the same witness.'},
            {'topic': 'observation window', 'resolution': 'Factory lifetime and baseline query come from different actual executions. Retaining the later baseline query is essential: earlier77 add/remove without a baseline occurred in one window and is not itself a trustworthy complete removal witness.'},
            {'topic': 'assembly', 'resolution': 'Move original createRemoved declaration before initial pair additions; leave baseline observation, target remove, and both assertions unchanged. This combines early lifetime with a drained observation window.'},
        ])
        d['alternative_focal_observation'] = {k: copy.deepcopy(b[k]) for k in
            ('target_operation', 'missing_factors', 'oracle_availability', 'minimal_assembly')}
        extent = 'exact_early_factory_lifetime_transferred_to_existing_observation_window_and_removal_check'

    if 'fragment_compatibility' not in d:
        d['fragment_compatibility'] = {
            'status': 'source_supported_proposal', 'cross_unit_transfer_support': True,
            'factor_mappings': [{'factor_id': f['factor_id'], 'mapping': f['compatibility']} for f in d['missing_factors']],
            'executed_joint_compatibility': False,
        }
    classes = [f['provenance_class'] for f in d['missing_factors']]
    d['counts'] = {
        'missing_factor_count': len(classes),
        'missing_exact': classes.count('Exact Executed Fragment'),
        'missing_related': classes.count('Related Executed Components'),
        'missing_absent': classes.count('Absent'),
        'missing_unresolved': classes.count(None),
        'has_missing_exact_fragment': 'Exact Executed Fragment' in classes,
        'all_missing_factors_exact': bool(classes) and all(x == 'Exact Executed Fragment' for x in classes),
        'all_missing_factors_have_executed_components': bool(classes) and all(x in ['Exact Executed Fragment', 'Related Executed Components'] for x in classes),
        'history_evidence_extent': extent,
        'cross_unit_transfer_support': True,
        'complete_historical_witness': d['historical_joint_witness']['complete_assertion_witness'],
        'manual_validated_assembly': False, 'automatic_validated_assembly': False,
    }
    write(OBS / f'adjudicated/{case}.json', d)
    print(case, d['counts'])
