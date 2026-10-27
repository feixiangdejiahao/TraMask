"""Root decisions preserve failed witnesses, wrong oracles and ambiguity."""
import copy
from root_record_io import start, finish


d, reviews, raw = start('S005', 'B')
d['minimal_assembly']['new_external_primitive_knowledge'] = 0
d['minimal_assembly']['proposal'] = 'In executed recursive-array diagnostic211, replace children.items direct recursive ref with anyOf[that ref,string] from220; retain all three original sample values and require construction plus true/true/false results instead of catch-and-print.'
d['historical_joint_witness'].update(reason='Recursive array and recursive anyOf ran separately; array-items recursive union did not appear as a complete executed witness.')
d['additional_reviewed_witnesses'] = [{'reviewer': 'A', 'minimal_assembly': copy.deepcopy(reviews['A']['minimal_assembly']),
    'relationship_to_primary': 'Broader same-failure reconstruction adds separate Meta constraints and newly assembled data. Actual Verifier failure occurs at type construction, so necessity of these extra conditions is unestablished.'}]
finish(d, raw, actions_checked=['s211_c0', 's220_c0', 's261_c0', 's264_c0'], extent='related_recursive_union_and_array_components_with_check_hardening', notes=[
    'Sole actual failure is ParseError constructing Tree within a non-structural schema, before any nested value oracle executes.',
    'Select B\'s two-unit hypothesis: array-ref diagnostic211 and hard-asserting recursive-anyOf220. Step211 actually prints leaf true,nested true,bad child false; named recursive-anyOf passes261, full suite61passing264.',
    'The schema object is the converter\'s target input, hence its structural change is Trigger. Keeping the diagnostic catch-and-print would swallow the focal exception; Check hardening is a necessary separate change.',
    'Two units, one external union transfer, two new relations/decisions (union at array-items position and hard pass/fail for the composed schema); no new external primitive. Sufficiency remains unexecuted.',
    'A\'s three-unit larger proposal is retained, not treated as a demonstrated minimum.'
])

d, reviews, raw = start('S007', 'B')
d['minimal_assembly']['new_external_primitive_knowledge'] = 0
d['minimal_assembly']['proposal'] = 'Keep complete test_warm_cache command, returncode0 and cache-summary assertions. Replace empty stdout bytes assertion with json.loads(proc.stdout.decode()) and results==[], reusing normal incremental JSON observation.'
d['historical_joint_witness'].update(reason='Warm-cache JSON input already executes but the final hard oracle incorrectly expects empty bytes. Existing normal JSON decoding/results check does not form a correct warm-cache witness.', wrong_effect_observed='Step42 reports exit0 and stdout bytes0 for --warm-cache -f json.')
finish(d, raw, actions_checked=['s42_c0', 's67_c0', 's97_c0'], extent='related_json_observer_transfer_replaces_wrong_oracle', notes=[
    'Both reviews select the same exact invocation and actual JSONDecodeError. There is no missing warm-cache stimulus or fresh-cache context in the original test.',
    'Definition67 explicitly asserts b-empty stdout; final97 reports320passed. This is a wrong Check, not a missing run.',
    'Normal incremental tests in67 execute JSON decoding and results observation. Apply those observer components to warm-cache, deriving empty results from the issue.',
    'Do not copy the entire _run_json helper: it adds --exit-zero, which would weaken the original warm-cache exit0 obligation. Transfer only decoding/results checks.',
    'Two units, two observer fragments, one new warm-cache output relation. No P/R assembly result yet.'
])

d, reviews, raw = start('S008')
public_bridge = copy.deepcopy(d['missing_factors'][1])
d['missing_factors'] = d['missing_factors'][:1]
d['required_factor_inventory'] = [f for f in d['required_factor_inventory'] if f.get('missing_factor_id') != public_bridge['factor_id']]
d['public_focal_bridge'] = {
    'actual_focal': 'Official metrics069/071/073 classify explicit full-enabled-set suppression as specific; P records nosec1 rather than0.',
    'historical_internal_witness': 'SelectorTests.test_glob expects the explicit five-ID set; restoring pre75 enabled-set exposes the same full-set-to-blanket conversion inside P.',
    'missing_for_portable_public_witness': public_bridge,
    'status': 'New public observation and independently justified classification required; not included in the one-unit historical restoration count.'
}
d['minimal_assembly'].update(proposed_source_units=1, historical_executed_versions=2,
    proposal='In the complete named test_glob, restore the enabled set without unrelated B101 from the actual step74 failure. Preserve selector B60* and the existing five-ID expected set.',
    scope='Internal historical witness restoration only; not a completed portable manager metrics test.')
d['historical_joint_witness'] = {'complete_assertion_witness': True,
    'scope': 'Internal explicit-selector classification witness, not the official public metrics assertion.',
    'history_actions': ['s70_c0', 's74_c0', 's75_c0'],
    'production_version': 'Step74 fails the full-set test; step75 adds B101 to enabled set and same38tests pass.',
    'classification': 'historical_witness_restore_baseline',
    'final_patch_rerun_status': 'not_executed_in_this_study'}
d['reference_compatibility_audit'] = {'status': 'unresolved_internal_api',
    'evidence': 'P test calls Agent-added nosec._resolve_selector and Suppression.tests. Official R patch does not define these symbols.',
    'implication': 'Cannot count internal restoration as identical-test PFAIL/RPASS until a compatible independent implementation is established. A public metrics witness is a separate new observation.'}
d['additional_reviewed_witnesses'] = [{'reviewer': 'B', 'target_operation': copy.deepcopy(reviews['B']['target_operation']),
    'minimal_assembly': copy.deepcopy(reviews['B']['minimal_assembly']),
    'relationship_to_primary': 'Distinct closing-parenthesis-only region failure058. Original diagnostic is print-only; requires source placement and Check edits. Retain auto-dedent contract ambiguity.'}]
finish(d, raw, actions_checked=['s70_c0', 's74_c0', 's75_c0'], extent='historical_internal_witness_weakened_public_oracle_bridge_unresolved', notes=[
    'A and B choose different actual Verifier failures. Primary is A\'s full-enabled-set classification; B\'s statement-range failure remains separate.',
    'Root counts one logical test_glob in two versions, not two independently authored tests. Step74 is an actual failed assertion despite shell pipeline returncode0; step75 changes setup by adding B101 and all38tests pass.',
    'The historical full witness observes internal selector classification. A also lists a new public metrics Check, but that Check is not part of its proposed restoration; root separates it explicitly.',
    'The task distinguishes blanket from specific resolved sets but does not spell out whether equal-to-enabled explicit sets become blanket. Preserve this oracle interpretation boundary alongside the independent historical specific-set expectation.',
    'Reference API compatibility is unresolved. No candidate execution or validated repair is claimed, and this case is not evidence of dispersed fragment assembly.'
], compatibility='unresolved_internal_api_and_public_metrics_bridge')

d, reviews, raw = start('S009')
d['missing_factors'][0]['role'] = 'Trigger'
for f in d['required_factor_inventory']:
    if f.get('missing_factor_id') == d['missing_factors'][0]['factor_id']:
        f['role'] = 'Trigger'
d['minimal_assembly']['new_external_primitive_knowledge'] = None
d['historical_joint_witness'].update(reason='Inline nonretroactivity and multiline suppression execute in distinct scripts57; no closing-only-active witness with a resolved oracle is established.')
d['oracle_availability']['status'] = 'unresolved_indentation_vs_statement_continuation'
d['oracle_availability']['available_to_blind_system'] = None
finish(d, raw, actions_checked=['s57_c0', 's61_c0', 's64_c0', 's89_c0'], extent='related_input_components_with_unresolved_boundary_oracle', notes=[
    'Sole official failure058 retains B602; all69F2P pass. The directive is on an indented last argument and its next physical line is the unindented closing parenthesis.',
    'Issue says begin acts only on subsequent physical lines and indented regions auto-end on smaller indentation. Whether statement continuation overrides this auto-dedent rule is not resolved by the wording; do not assume Verifier expectation alone settles it.',
    'Primary A retains Related provenance for actual inline-begin and multiline-region components, and null Check provenance for the unsettled exact-boundary oracle. B\'s Absent complete-condition label should not erase those executed components.',
    'The changed comments and line layout are input to the scanner, hence Trigger rather than prior Context. Both historical57 scripts merely print findings/metrics; B\'s base check_kind assertion is incorrect.',
    'Named functional test64 genuinely passes and provides another hard regional suppression check, but it is not part of the selected two-script minimal hypothesis. Adding it would require counting a third source unit.',
    'Two distinct diagnostic scripts despite a shared tool call, one transferred placement component, new joint placement and hard decision; correctness remains unresolved and no execution-positive claim is made.'
], compatibility='unresolved_task_oracle')
