"""Explicit root adjudications after reading both reviews and original receipts."""
import copy
from root_record_io import start, finish


def width_is_trigger(d, factor_id):
    for field in ['missing_factors', 'required_factor_inventory']:
        for f in d[field]:
            if f.get('factor_id') == factor_id or f.get('missing_factor_id') == factor_id:
                f['role'] = 'Trigger'
                f['role_adjudication'] = 'Width is an explicit argument of the target truncation call, not prior environment state.'


d, reviews, raw = start('S077')
width_is_trigger(d, 'F1')
d['minimal_assembly']['proposal'] = 'In complete TestOutputTruncatePreserveResetsFromDefault, change width 5 to 100 and use the full bar expectation already executed in TestStyleTruncatePreserveResetsFits. Keep Output receiver, ANSI input and preserve default.'
d['historical_joint_witness'].update(reason='Style full-fit witness and Output clipped witness both passed; no complete Output full-fit preserve witness was found.', production_version='Authored tests passed at 72/74 and were removed at 78. The post-removal suite is not execution evidence for these units.')
finish(d, raw, actions_checked=['s38_c0', 's68_c0', 's72_c0', 's74_c0', 's78_c0'], extent='exact_trigger_with_related_cross_api_check', notes=[
    'Both reviewers choose the same actual Output full-fit reset-reopening failure. Both agree on two source units and the existing full ANSI expected bytes.',
    'Root classifies requested width as Trigger: it changes an argument of the operation. The preserve default is Context already present in the base.',
    'The full output bytes were executed under Style.Truncate; applying that oracle to Output.Truncate is a new cross-API relation, therefore Related Check rather than Exact Check.',
    'Step 72 is uncached execution of both packages before deletion. Step 74 also passes; step 78 removes the authored tests and cannot substantiate their execution.',
    'Two source units, two transferred fragments, one new applicability relation, zero new external semantic primitive. No assembly has been executed here.'
])

d, reviews, raw = start('S078', 'B')
d['minimal_assembly']['new_external_primitive_knowledge'] = 0
d['minimal_assembly']['proposal'] = 'Retain complete TestStylePreserveResets setup and input, replace s.Truncate(10, ...) with s.String(), and change the expected visible suffix from worl to world while preserving one outer final reset.'
d['historical_joint_witness'].update(reason='The reset-bearing preserve style is checked through Truncate; stock TestRendering checks String without an internal reset. The full joint String witness was not found.')
finish(d, raw, actions_checked=['s6_c0', 's29_c0', 's30_c0', 's66_c0', 's76_c0'], extent='exact_api_trigger_with_related_rendering_check', notes=[
    'The official failure is ordinary Style.String ignoring preserve-resets; both reviewers select this same obligation.',
    'Use B\'s two-unit proposal: stock TestRendering supplies the actual direct public String call, while the base already supplies reset input, preserve state and reopening expectation. A\'s third ANSI full-fit donor is optional, not required for this smaller proposal.',
    'String on an existing styled receiver is Exact Trigger under role-preserving object mapping. A labels the full combined condition Related; that new joint applicability is counted in Check, without relabeling the already executed API itself.',
    'Step 29 fails compilation due to an unused strings import. Step 30 removes it and reaches tests but has a separate template failure. Step 76 uncached full-suite PASS establishes both chosen units.',
    'The full String expected output must be derived from the original text and executed reset rule. Do not copy the extra trailing reset/reopen pair in A\'s ANSI full-fit test.',
    'Two historical units, one transferred API fragment, one new full-output relation, zero external primitives; requires Trigger and Check edits, not context-only repair.'
])

d, reviews, raw = start('S079')
d['minimal_assembly']['historical_executed_versions'] = 2
d['minimal_assembly']['proposal'] = 'Restore want Hello in the ascii no tail row of the original complete TestStyleTruncate table; retain input Hello World, max 5, Ascii profile and tail option.'
d['historical_joint_witness'] = {
    'complete_assertion_witness': True,
    'history_actions': ['s27_c0', 's39_c0'],
    'production_version': 'Earlier implementation before step 40; complete correct row passed in both 27 and uncached 39.',
    'later_change': 'Step 40 replaces ASCII truncation with return t.string and changes this row\'s expected Hello to Hello World in the same call; the modified suite passes.',
    'classification': 'historical_witness_restore_baseline',
    'final_patch_rerun_status': 'not_executed_in_this_study',
    'unit_scope': 'One logical test row in two historical versions, not two independently authored source units.'
}
d['additional_reviewed_witnesses'] = [{
    'reviewer': 'B', 'target_operation': copy.deepcopy(reviews['B']['target_operation']),
    'minimal_assembly': copy.deepcopy(reviews['B']['minimal_assembly']),
    'relationship_to_primary': 'Distinct actual String/preserve failure; two-source API transfer with a derived full-output Check. Preserve as an additional task defect, not evidence for the ASCII focal failure.'
}]
finish(d, raw, actions_checked=['s27_c0', 's39_c0', 's40_c0', 's43_c0'], extent='complete_correct_historical_witness_later_weakened', notes=[
    'A selects actual ASCII width failure; B selects actual ordinary String preserve failure. Root freezes A as primary and retains B separately.',
    'The width-limited Hello oracle and all its trigger/context already formed one executed test. Restoring it is a historical-unit baseline, not a newly assembled fragmentation success.',
    'The historical correct witness passed on earlier production; the record does not show its failure on the final patch, because production and expected value changed together in 40.',
    'Step 43 deletes both authored test files before rerunning. That later green result does not establish execution of the removed rows.',
    'Full original table must be evaluated as proposed; other rows have separately uncertain expectations, including redundant reset sequences. Do not silently narrow to the ASCII row after a reference failure.',
    'One logical source unit, two executed versions, one restored Check, zero new semantic elements. No new P/R runs.'
], compatibility='source_supported_restoration_proposal_full_table_reference_pending')

d, reviews, raw = start('S080', 'B')
width_is_trigger(d, 'F3')
d['minimal_assembly']['new_external_primitive_knowledge'] = 0
d['minimal_assembly']['proposal'] = 'Keep both branches of TestOutputTruncatePreserveResetsDefault; change both requested widths 7 to 20 and the common expected suffix wo to world, preserving the reopening and final reset.'
d['historical_joint_witness'].update(reason='No complete full-fit Output preserve witness found. The plain full-fit and clipped Output reset expectations were executed separately.')
finish(d, raw, actions_checked=['s24_c0', 's32_c0', 's38_c0', 's65_c0'], extent='exact_width_trigger_with_related_full_output_check', notes=[
    'Both reviewers select the same actual Output full-fit failure. Use B\'s plain no-clipping donor and existing base reopening Check; A\'s hyperlink width11 donor is an alternative.',
    'Root corrects width Context to Trigger because the numeric width is an argument of Output.Truncate. Both branches alter one semantic width condition at two sites.',
    'The actual base string hello+world has 10 visible characters, not the 11 described in B\'s reached_evidence. Width20 exceeds either length and is present in the executed plain-string donor.',
    'A calls full Check Absent. Root adopts Related: the base already hard-checks reopening and the donor hard-checks preservation of complete text at fitting width. Their applicability together is new, but no absent semantic primitive is needed.',
    'Step24 explicitly reports PASS for the selected base despite another CSI test failing. Step32 explicitly reports PASS for the hyperlink alternative despite another reset test failing. Step65 is uncached full-suite PASS.',
    'Two source units, one transferred width condition, one newly composed complete-output expectation. Source-unit count includes the base; its existing check is not counted as a second external donor.'
])
