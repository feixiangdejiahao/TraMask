"""Root adjudications from paired independent reviews and checked primary evidence.

This informed observation artifact is never supplied to the blind generator.
S046--49 were adjudicated separately; S054 awaits historical source recovery.
"""
from pathlib import Path
import copy
import hashlib
import json

OBS = Path(__file__).resolve().parent
RUN = OBS.parent
CASES = ['S043', 'S044', 'S045', 'S050', 'S051', 'S052', 'S053', 'S055', 'S056']


def read(path):
    return json.loads(path.read_text())


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def receipt(path):
    raw = path.read_bytes()
    return {'path': str(path), 'bytes': len(raw), 'sha256': sha(raw)}


def action_receipt(action):
    return {k: action[k] for k in ('id', 'step_id', 'call_index', 'tool_call_id',
                                  'command_sha256', 'observation_content_sha256')}


for case in CASES:
    reviews = {r: read(OBS / f'reviewer_{r}/{case}.json') for r in ['A', 'B']}
    a, b = reviews['A'], reviews['B']
    assist_path = OBS / f'adjudication_assists/{case}.json'
    assist = read(assist_path)
    sources = read(OBS / f'sources/{case}.json')['sources']
    actions = {x['id']: x for x in read(RUN / f'public_inputs/{case}/history.json')['actions']}
    frozen = {}
    for role in ['A', 'B']:
        src = OBS / f'reviewer_{role}/{case}.json'
        assert receipt(src)['sha256'] == assist['review_receipts'][role]['sha256']
        dst = OBS / f'frozen_reviews/{role}/{case}.json'
        dst.parent.mkdir(parents=True, exist_ok=True)
        raw = src.read_bytes()
        if dst.exists():
            assert dst.read_bytes() == raw
        else:
            dst.write_bytes(raw)
        frozen[role] = {'path': str(dst.relative_to(RUN)), 'sha256': sha(raw)}

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
            'new_external_primitive_knowledge': 0,
            'source_proposals': {r: copy.deepcopy(x['minimal_assembly']) for r, x in reviews.items()},
            'execution_validated_minimum': None,
        },
        'historical_joint_witness': {'complete_assertion_witness': False},
        'execution': {'status': 'not_executed_in_this_study',
                      'manual_assembly_success': False, 'blind_result': False},
        'adjudication_assist': receipt(assist_path),
        'original_failure_assertion': copy.deepcopy(assist['original_failure_assertion_checked']),
        'root_source_checks': [], 'adjudication_notes': [],
        'remaining_work_for_goal': [
            'Finish all88 informed observations and freeze before blind generation',
            'Run automatically selected candidates and historical-unit controls independently',
        ],
    }
    d['oracle_availability']['independent_source_receipts'] = [sources[k] for k in
        ['issue', 'verifier_test', 'reference_solution']]
    notes = d['adjudication_notes']

    if case == 'S043':
        d['fragment_compatibility'] = {
            'status': 'source_supported_joint_query_proposal',
            'mapping': 'Retain A non-first pair test; create and drain the exact joint query before focal addition, then use Added(pair) AND Added(relation) and expected empty result.',
            'cursor_requirement': 'Keep existing separate baseline drains, but they do not establish a new joint query cursor. Prime the exact joint query before adding the focal pair.',
            'preserved_semantics': 'Non-first pair event is true while relation-trait event is false; conjunction must be false.',
            'changed_semantics': 'New joint target query and derived joint Check. This is not context-only repair.',
            'executed_joint_compatibility': False,
        }
        d['missing_factors'][0]['compatibility']['requirements'] += ' Prime the exact joint query before focal addition; separate query drains alone are insufficient.'
        d['minimal_assembly']['derived_joint_relations'] = ['Pair-level Added AND same-relation trait Added with a common observation window.']
        d['alternative_base_proposal'] = {k: copy.deepcopy(b[k]) for k in
            ['agent_base_units', 'missing_factors', 'minimal_assembly']}
        notes.extend([
            {'topic': 'base-dependent missing factors', 'resolution': 'A begins with non-first pair history and separate pair/trait observations. B begins with static-AND include/exclude assertions. Both propose the same new event conjunction; retain A as primary and B separately, without pooling their missing-factor flags.'},
            {'topic': 'source cardinality', 'resolution': 'Two distinct named tests, though both pass in suite105. The same donor span supports both new query and derived oracle; it is one transfer, not two source units.'},
        ])
        checked = ['s99_c0', 's105_c0']
        extent = 'related_joint_event_query_and_check_from_two_executed_tests'

    elif case == 'S044':
        d['witness_status'] = 'static_type_contract_confirmed_runtime_not_executed'
        d['minimal_assembly'].update(proposed_source_units=1,
            logical_test_functions=1, historical_assertion_spans=2,
            source_unit_granularity='Both assertions are in testWindowFunctions; one function-level unit, two assertion spans.',
            derived_joint_relations=['Apply explicit output-type argument to ranking helper while retaining exact expected builder type.'])
        d['measurement_scope'] = {'kind': 'static_api_contract', 'runtime_defect_confirmed': False,
                                  'runtime_context_repair': False}
        notes.extend([
            {'topic': 'Trigger versus Context', 'resolution': 'Supplying <number> changes the compiler input/API call. Retain A Trigger classification; B Context label describes the same edit but is not a runtime state condition.'},
            {'topic': 'checker execution', 'resolution': 'Actual99 and117 tsd commands check nongeneric ranking and generic value calls. Their function bodies need not execute as JavaScript for compiler validation. Archived eight TS2558 errors precede all254 missing F2P results; missing cases are not executed runtime failures.'},
            {'topic': 'source-unit granularity', 'resolution': 'Both reviewers count two assertion-level units. Canonical count is one named function plus two spans, preserving the finer review counts. This is within-unit transfer, not cross-test fragmentation.'},
        ])
        checked = ['s99_c0', 's117_c0']
        extent = 'related_generic_call_transfer_within_one_static_test_function'

    elif case == 'S045':
        d['historical_joint_witness'] = {
            'complete_assertion_witness': True,
            'history_category': 'complete_failed_witness_later_scheduling_context_weakened',
            'definition': action_receipt(actions['s57_c0']),
            'execution': action_receipt(actions['s67_c0']),
            'weakening': action_receipt(actions['s91_c0']),
            'original_failure': 'The final failure list explicitly contains batch coalesces for immediate f and repeated input vector.',
            'later_change': 'Insert time.sleep(0.1) in f, retaining the input vector and distinct-call-count condition; batch coalescing then passes.',
            'production_version': 'Historical failure is on an earlier implementation. It is not a new final-P/R execution.',
        }
        d['minimal_assembly'].update(logical_test_functions=1, source_versions=2,
            method_category='restore_historical_fast_witness_or_full_unit_rerun',
            derived_joint_relations=[])
        notes.extend([
            {'topic': 'agreement', 'resolution': 'Both reviewers find the same complete early witness and subsequent added delay. Independent fast-clear unit is unnecessary for the minimum recovery.'},
            {'topic': 'baseline', 'resolution': 'Report historical-unit rerun separately. Reinstating an already complete failure test is not evidence of previously dispersed ingredients.'},
            {'topic': 'timing', 'resolution': 'The task specifies per-item batch coalescing. Preserve the full batch vector and both checks, remove only the sleep, and repeat P/R runs before claiming detection.'},
        ])
        checked = ['s57_c0', 's67_c0', 's91_c0', 's116_c0']
        extent = 'exact_context_restore_but_complete_failed_witness_already_executed'

    elif case == 'S050':
        d['minimal_assembly']['derived_joint_relations'] = []
        notes.extend([
            {'topic': 'actual failure location', 'resolution': 'Despite a carries_across_runs test name, archived failure is first-cycle1 versus2. The selected defect is duplicate watch registration consuming a finite global cap, not later-cycle state persistence.'},
            {'topic': 'execution reachability', 'resolution': 'Definition32 initially stops before config+CLI donor;33 runs through that section and ALL OK. Base59 independently passes cap2 with six files over two distinct watches.'},
            {'topic': 'route equivalence', 'resolution': 'Historical CLI+config duplicates the same physical watch; Verifier uses CLI+positional duplication. Transfer the former into base59 and retain its file fixtures and len(moved)==2. Semantic aliasing is Exact; equivalence of resulting implementation paths remains to be executed.'},
        ])
        checked = ['s32_c0', 's33_c0', 's59_c0']
        extent = 'exact_duplicate_watch_context_transfer_into_existing_global_cap_test'

    elif case == 'S051':
        # Related support exists, but neither reviewer finds the complete correct
        # n>1 far-reflection rule in executed validation history.
        original = d['missing_factors'][0]
        original['provenance_class'] = 'Related Executed Components'
        original['source_fragments'] = copy.deepcopy(b['missing_factors'][0]['source_fragments'])
        original['exact_full_oracle_present'] = False
        original['absent_semantic_primitive'] = 'Single reflection followed by cval fallback for length>1 far indices is supplied by Issue, not the historical size1 special-case assertion.'
        original['compatibility'] = copy.deepcopy(b['missing_factors'][0]['compatibility'])
        for factor in d['required_factor_inventory']:
            if factor.get('role') == 'Check' and not factor.get('present_in_base'):
                factor['history_provenance'] = 'Related Executed Components'
                if 'provenance_class' in factor:
                    factor['provenance_class'] = 'Related Executed Components'
        d['minimal_assembly'].update(proposed_source_units=2, proposed_transferred_fragments=1,
            issue_only_alternative={'source_units': 1, 'transferred_fragments': 0,
                                    'new_semantic_elements': 1},
            derived_joint_relations=['Generalize unreflectable-access fallback to existing far offsets using Issue, then sum two default-zero contributions.'])
        d['oracle_availability'].update(historical_check_provenance='Related Executed Components',
            complete_expected_vector_in_history=False,
            reason='Issue supplies the n>1 single-reflection rule. Donor136 supplies only the actually checked size1 unreflectable-access-to-cval relation.')
        notes.extend([
            {'topic': 'provenance disagreement', 'resolution': 'A correctly finds the full n>1 far-offset oracle absent. B identifies a specific cval fallback component in an executed1x1 test. Record partial Related support and the absent rule explicitly; do not claim all required knowledge was historical.'},
            {'topic': 'minimality', 'resolution': 'Two units are needed only for the historical-donor version. A one-unit Issue-derived correction remains an alternative, so no artificial two-unit lower bound is claimed.'},
            {'topic': 'correct oracle', 'resolution': 'Original178 already executes a[-100]+a[100] on length5 and passes a wrong modulo8 expected vector. Each once-reflected coordinate remains out of bounds, so both accesses contribute default0. Only the Check changes.'},
        ])
        checked = ['s126_c0', 's136_c0', 's178_c0']
        extent = 'related_cval_component_but_full_nondegenerate_far_offset_oracle_new_from_issue'

    elif case == 'S052':
        # Preserve A's full parallel base; use B's genuinely independent executed
        # reference helper as the primary rule donor, instead of trusting SUT output.
        d['missing_factors'][0]['source_fragments'] = copy.deepcopy(b['missing_factors'][0]['source_fragments'])
        d['missing_factors'][0]['compatibility']['mapping'] = 'Retain A final parallel base194; replace its expected[-77,0,1] by the all-cval vector derived from actually executed helper24. Keep kernel, length3, cval-77, parallel mode and original comparison.'
        d['minimal_assembly']['primary_donor_ids'] = b['minimal_assembly']['selected_fragment_ids']
        d['minimal_assembly']['derived_joint_relations'] = ['Evaluate historical one-reflection helper for each original stencil position and use it as parallel-output expectation.']
        d['historical_joint_witness'].update(correct_independent_rule_executed=True,
            exact_correct_sut_output_observed=True, complete_correct_sut_assertion_executed=False)
        notes.extend([
            {'topic': 'donor strength', 'resolution': 'Root inspected helper24 with if/elif then bounds validity and cval fallback, and its actual far-index outputs. This is stronger independent support than earlier SUT output70. Retain output70 only as corroboration, not self-validating ground truth.'},
            {'topic': 'base consistency', 'resolution': 'Canonical base remains A parallel194. B committed130 direct/njit/parallel test is retained as an alternative; its artifacts are not silently substituted for base194.'},
            {'topic': 'oracle construction', 'resolution': 'For indices-5,-4,-3 and length3, single reflection gives5,4,3, all invalid. All-cval[-77,-77,-77] is derived from a historical executed rule, but no complete correct stencil comparison was found.'},
        ])
        checked = ['s24_c0', 's70_c0', 's194_c0']
        extent = 'related_independent_reflection_rule_available_but_not_applied_to_existing_parallel_check'

    elif case == 'S053':
        d['minimal_assembly']['derived_joint_relations'] = ['Apply independently observed symmetric edge-repetition map to existing neighbor-sum expected helper.']
        notes.extend([
            {'topic': 'agreement', 'resolution': 'Both reviewers find correct NumPy symmetric mapping at20 and incorrect-i expected helper in the actual stencil unit132/177/183. Keep A helper edit-i→-i-1 as primary; B np.pad-slice composition is an alternative.'},
            {'topic': 'oracle scope', 'resolution': 'The radius1 kernel has expected[1,3,6,9,11] for arange5. NumPy repeated-padding behavior supplies the nearby edge map; it is not a valid donor for far-offset cval semantics in S051/S052.'},
            {'topic': 'repair type', 'resolution': 'Target and boundary context already execute. The proposed edit repairs the Check, not context; the full reference-to-stencil comparison is newly composed.'},
        ])
        checked = ['s20_c0', 's132_c0', 's177_c0', 's183_c0']
        extent = 'related_executed_reference_mapping_missing_from_final_stencil_oracle'

    elif case == 'S055':
        first = d['missing_factors'][0]
        first['provenance_class'] = 'Related Executed Components'
        first['specific_executed_components'] = [
            {'action': action_receipt(actions['s95_c0']), 'meaning': 'Top-level not invokes an entered failing inequality rule; Evals2/Successes1 establishes entry.'},
            {'action': action_receipt(actions['s98_c0']), 'meaning': 'Prepared successful allow body and hard parent Evals1/Successes1 check actually run.'},
        ]
        first['source_fragments'] = [copy.deepcopy(b['missing_factors'][0]['source_fragments'][0]),
                                     copy.deepcopy(a['missing_factors'][1]['source_fragments'][0])]
        first['absence_search']['scope_resolution'] = 'No complete nested-parent relation was found. Its specific top-level negation and successful-parent components exist, so the user-defined factor category is Related rather than wholly Absent.'
        first['compatibility']['mapping'] = 'Place actual entered-failure inequality from95 in a new blocked rule and put not blocked in existing prepared allow body. Preserve input useradmin and full original parent1/1 assertion.'
        for factor in d['required_factor_inventory']:
            if factor.get('inventory_id') == 'C1' or factor.get('missing_factor_id') == 'F1':
                factor['history_provenance'] = 'Related Executed Components'
        d['minimal_assembly']['derived_joint_relations'] = ['Place entered failing child negation inside active successful parent.']
        notes.extend([
            {'topic': 'mechanism reachability', 'resolution': 'Root inspected54: equality deny is pruned and output contains only allow. It cannot establish failed-child stack entry.95 inequality test explicitly produces Evals2/Successes1, so use A stronger donor and role-map banned toadmin.'},
            {'topic': 'provenance consistency', 'resolution': 'A calls the complete nested structure Absent; B calls component composition Related. Under the user definition and S038 precedent, root classifies nesting as Related because actual top-level negation and successful parent body are available, while marking the new nested relation explicitly. No claim is made that nested entry occurred historically.'},
            {'topic': 'semantic factors', 'resolution': 'Keep two conditions: new nesting relation and an actually entered failing predicate. Only the latter is Exact. Original parent1/1 oracle remains valid because negating the false child preserves parent truth. Mechanism control must confirm child entry in any execution.'},
        ])
        checked = ['s54_c0', 's95_c0', 's98_c0']
        extent = 'related_nested_relation_plus_exact_entered_failure_component_with_existing_parent_oracle'

    elif case == 'S056':
        d['fragment_compatibility'] = {
            'status': 'source_supported_proposal_reference_base_compatibility_unresolved',
            'mapping': 'A primary: explicitly run collapseGroups on the original first g>rect document, pass its returned SVG into unchanged convertShapeToPath, retain original subtree-preservation and unrelated-shape-conversion assertions.',
            'new_relation': 'Same document flows through an explicitly ordered prepass and original target operation.',
            'reference_compatibility': 'Original Agent test must first pass Reference; no such run has occurred.',
            'scope': 'First original logical g>rect case, with its two assertions; not the entire multi-scenario named function.',
            'executed_joint_compatibility': False,
        }
        d['alternative_base_proposal'] = {k: copy.deepcopy(b[k]) for k in
            ['target_operation', 'agent_base_units', 'missing_factors', 'minimal_assembly']}
        d['minimal_assembly']['derived_joint_relations'] = ['Explicit collapse-output-to-conversion-input sequence on the same original document.']
        d['original_failure_assertion_definition'] = copy.deepcopy(assist['verifier_assertion_definition_checked'])
        notes.extend([
            {'topic': 'different target boundaries', 'resolution': 'A retains the shape test and adds collapse prepass. B retains collapseGroups and constructs class-qualified group anchor plus new preservation oracle. Keep both proposals separate; they do not have the same missing-factor set.'},
            {'topic': 'archived outcome', 'resolution': 'Named child-anchor Verifier failure has no assertion message. test.patch binds that name to retaining g.keep and count1. This supports the defect family, not proof that A proposed sequence will reproduce it.'},
            {'topic': 'execution completion', 'resolution': '203 only starts the background cargo job.204 reads its terminal59passed result. The source read22 is not the execution; selected authored source140 and stock collapse unit are tied to203→204.'},
            {'topic': 'new relation', 'resolution': 'Turning on two flags does not prove pass order. Count explicit prepass dataflow as one new semantic relation, not glue. R compatibility and all candidate outcomes remain unexecuted.'},
        ])
        checked = ['s22_c0', 's140_c0', 's203_c0', 's204_c0']
        extent = 'related_cross_pass_composition_with_reference_compatibility_pending'

    d['root_source_checks'] = [
        {'action_receipts': [action_receipt(actions[x]) for x in checked],
         'finding': 'Root read primary command/source and actual output; decisions and limits are recorded in adjudication_notes.'},
        {'source': sources['issue'], 'finding': 'Root checked task semantics against selected target and proposed oracle.'},
    ]
    if 'fragment_compatibility' not in d:
        d['fragment_compatibility'] = {
            'status': 'source_supported_proposal',
            'factor_mappings': [{'factor_id': f['factor_id'], 'mapping': f['compatibility']}
                                for f in d['missing_factors']],
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
        'all_missing_factors_have_executed_components': bool(classes) and all(x in
            ['Exact Executed Fragment', 'Related Executed Components'] for x in classes),
        'historical_support_extent': extent,
        'complete_historical_joint_witness': d['historical_joint_witness']['complete_assertion_witness'],
        'manual_execution_validated': False, 'blind_execution_validated': False,
    }
    dest = OBS / f'adjudicated/{case}.json'
    with dest.open('x') as stream:
        json.dump(d, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
    print(case, extent)
