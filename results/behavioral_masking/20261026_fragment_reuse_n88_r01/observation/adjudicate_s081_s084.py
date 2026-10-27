"""Source-adjudicated observations, not candidate execution results."""
import copy
import hashlib
from root_record_io import start, finish, read, RUN


def alternative(d, r, relationship):
    d['additional_reviewed_witnesses'] = [{'reviewer': 'B',
        'target_operation': copy.deepcopy(r['target_operation']),
        'minimal_assembly': copy.deepcopy(r['minimal_assembly']),
        'relationship_to_primary': relationship}]


d, reviews, raw = start('S081')
alternative(d, reviews['B'], 'Distinct actual TAP output failure. Its app self-reference transfer is retained separately from App.getExitCode reason lookup.')
d['minimal_assembly']['proposal'] = 'Move bailReason: my failing test from the mocked getBailReport result onto app.reporter. Preserve testsRanBeforeBail:3 and all four original error.message assertions.'
d['historical_joint_witness'].update(reason='Direct subreporter tests use the correct public reporter shape; App exit test uses the nested wrong shape. No complete exit-reason witness using the correct shape found.')
finish(d, raw, actions_checked=['s79_c0', 's118_c0', 's155_c0', 's156_c0'], extent='exact_reporter_shape_context_transfer', notes=[
    'A and B select different actual failures. Root selects A because issue explicitly requires getExitCode to read bailReason property and testsRanBeforeBail from getBailReport.',
    'Step79 executes four direct reporter tests with bailReason on reporter, outside the returned report. Step118 executes the selected App test with bailReason incorrectly nested inside the report.',
    'Steps155/156 confirm both source suites run near submission. Preserve the original reason text by object/value mapping, not the donor f1 literal.',
    'The official error also has a count mismatch 4 versus5. This assembly isolates reason lookup with mocked count3 and does not claim to fix/detect the separate real Reporter count bookkeeping error.',
    'Two units, one semantic fixture-shape condition represented by removing and adding the property, no new semantic element. P/R execution remains pending.'
])

d, reviews, raw = start('S082')
alternative(d, reviews['B'], 'Distinct TAP output failure with a historically executed config-only app donor; retained separately from the pre-start ProcessTestRunner abort witness.')
d['minimal_assembly']['proposal'] = 'Remove only the no-op runner.onFinish assignment from the process abort fixture; retain the full two-abort Promise chain, killCount==1, finished==true and reporter.total==0.'
d['reference_compatibility_audit'] = {
    'status': 'unresolved_reference_idempotence_conflict',
    'evidence': 'Official R ProcessTestRunner.abort guards onFinish, but retains this.process and has no repeated-abort guard. With this original fake kill function, both abort calls appear to invoke kill, conflicting with original killCount==1.',
    'implication': 'The unedited complete base and candidate require actual R qualification. A guard for the target exception alone does not establish a correct reference for every original assertion.',
    'execution': 'Static reference inspection only; no new P/R runs.'
}
finish(d, raw, actions_checked=['s127_c0', 's174_c0'], extent='absent_prestart_callback_context_reference_conflict', notes=[
    'A selects actual TypeError this.onFinish is not a function in the pre-start abort operation. B selects a different TAP output bug.',
    'The selected fixture has fake process and onStart/onEnd/onFinish callbacks. Removing onFinish exposes a state absent from the cited executed abort units, while keeping the existing target and assertions.',
    'Step127 explicitly creates and runs these runner tests; final174 lists the same files and reports273 passing. Historical execution does not prove the original unit passes on R.',
    'Root inspected official solution: it guards missing onFinish but appears to call the unchanged fake process.kill twice. Keep this reference compatibility conflict rather than declaring the context edit a validated repair.',
    'One source unit, no donor fragment, one new lifecycle condition derived from the public abort contract. No successful assembly claimed.'
], compatibility='unresolved_original_reference_idempotence_contract')

d, reviews, raw = start('S083')
h = {a['id']: a for a in read(RUN / 'public_inputs/S083/history.json')['actions']}
definition, execution = h['s83_c0'], h['s85_c0']
code = "expect(global.emit).to.have.been.calledOnce();\n      expect(global.emit).to.have.been.calledWith('all-test-results');"
assert code in definition['command']
fragment = {
    'fragment_id': 'same_unit_final_completion_check', 'source_unit_id': d['agent_base_units'][0]['unit_id'],
    'statement_or_condition': 'Original unit hard-checks one all-test-results notification after two jasmineDone calls.',
    'code': code, 'code_sha256': hashlib.sha256(code.encode()).hexdigest(),
    'code_span': {'kind': 'exact_command_span', 'command_action': 's83_c0',
                  'start_char': definition['command'].index(code), 'end_char': definition['command'].index(code) + len(code)},
    'step_id': 85, 'call_index': 0, 'tool_call_id': execution['tool_call_id'],
    'command_sha256': execution['command_sha256'], 'observation_sha256': execution['observation_content_sha256'],
    'completion_observation_action': 's85_c0',
    'execution_reachability': 'After sandbox and module export fixes, step85 explicitly reports the Jasmine suppresses-events/signals-once test passing; final134 includes458passing.'
}
f = d['missing_factors'][0]
f['provenance_class'] = 'Related Executed Components'
f['source_fragments'] = [fragment]
f['compatibility']['requirements'] = 'Expected event and once-only obligation were executed later in this same unit; applicability immediately after aborted specDone is a new temporal relation.'
for inv in d['required_factor_inventory']:
    if inv.get('missing_factor_id') == f['factor_id']:
        inv['history_provenance'] = 'Related Executed Components'
d['oracle_availability']['historical_check_provenance'] = 'Related Executed Components'
d['minimal_assembly']['proposed_transferred_fragments'] = 0
d['minimal_assembly']['same_unit_reused_check_fragments'] = 1
d['minimal_assembly']['proposal'] = 'Duplicate the existing completion assertions immediately after specDone and before the first jasmineDone; retain both later completion calls and original assertions.'
d['reference_compatibility_audit'] = {'status': 'adapter_module_loading_requires_qualification',
    'evidence': 'Original authored test imports jasmine2_adapter as a CommonJS function, enabled by production export addition85. Official R patch supplies correct aborted specDone notification but does not include that export.',
    'implication': 'Original harness may fail before reaching assertions on R. Any portable loading adaptation must be explicit and identical on P/R; do not edit production to make the test work.'}
alternative(d, reviews['B'], 'Distinct numeric post-reset testsRanBeforeBail check; two executed units support count observation and clearing semantics. Exact numeric0 is not explicitly stated by issue; preserve the oracle derivation separately.')
finish(d, raw, actions_checked=['s72_c0', 's77_c0', 's83_c0', 's84_c0', 's85_c0', 's89_c0', 's134_c0'], extent='same_unit_related_check_at_new_lifecycle_boundary', notes=[
    'Root selects A\'s aborted Jasmine specDone failure; B\'s reset count failure remains an additional witness.',
    'Abort state and specDone already execute in the original test. The original completion Check runs only after native jasmineDone, allowing this failure to pass.',
    'A calls the missing early Check Absent. Root uses Related: the same unit has a specific executed once-only all-test-results expectation, not merely generic assertion syntax. Its new earlier temporal applicability is still a new semantic relation.',
    'Step83 fails in beforeEach because sandbox is undefined; step84 still fails module import. Step85 explicitly reaches and passes this named Jasmine test after adding exports; final134 has458passing and2pending.',
    'One source unit and one reused same-unit check, no external donor; one new timing relation. This is observation placement repair rather than cross-test combination.',
    'Reference module loading is unresolved and must be qualified before any PFAIL/RPASS claim.'
], compatibility='source_supported_temporal_check_reference_loader_pending')

d, reviews, raw = start('S084')
f = d['missing_factors'][0]
f['role'] = 'Trigger'
f['semantic_condition'] = 'One shortcut input combines unshifted key code97, Alt+Shift modifier4, repeat phase2 and associated text65 in modifier:phase;text order.'
f['compatibility']['mapping'] = 'Original Alt+Shift row ESC[65;4u becomes ESC[97;4:2;65u. Retain existing expected alt+shift+a, character None, modifiers, base a and shifted A, and complete parameterized assertions.'
f['compatibility']['requirements'] = 'Three literal input fields change: normalize key65 to97 using the executed shift/text donor, add phase2 and text65. Phase/text components existed separately; the valid joint field relation is newly assembled.'
for inv in d['required_factor_inventory']:
    if inv.get('missing_factor_id') == f['factor_id']:
        inv['role'] = 'Trigger'
        inv['semantic_condition'] = f['semantic_condition']
d['minimal_assembly']['proposal'] = f['compatibility']['mapping']
d['minimal_assembly']['semantic_field_edits'] = 3
d['minimal_assembly']['source_granularity'] = 'Three logical units: selected Alt+Shift parameter row, separate shift/text parameter row, and phase test function; two enclosing test functions.'
d['minimal_assembly']['atomic_component_provenance'] = [
    {'component': 'repeat phase2 attached to modifier', 'class': 'Exact Executed Fragment', 'source': 'phase118'},
    {'component': 'unshifted97 with shift modifier and associated text65', 'class': 'Exact Executed Fragment', 'source': 'text118_row'},
    {'component': 'valid phase-plus-text order in one event', 'class': 'Related Executed Components', 'new_joint_relation': True}
]
d['independent_protocol_audit'] = {
    'url': 'https://sw.kovidgoyal.net/kitty/keyboard-protocol/', 'access_date': '2026-10-27',
    'sections': ['An overview', 'Key codes', 'Event types', 'Text as code points'],
    'short_grammar_quote': 'CSI unicode-key-code:alternate-key-codes ; modifiers:event-type ; text-as-codepoints u',
    'paraphrase': 'The key code is unshifted; phase is a colon subfield of modifiers, before the semicolon-separated associated text. Repeat is2.',
    'use': 'Independent informed-stage validation only; do not add this retrieved page or root correction to blind inputs.',
    'blind_complete_grammar_availability': None
}
d['oracle_availability']['available_to_blind_system'] = None
d['oracle_availability']['reason'] = 'Issue supplies stable shortcut metadata and historical units supply individual field behavior; complete grammar availability to blind generation has not been established.'
finish(d, raw, actions_checked=['s81_c0', 's82_c0', 's118_c0', 's119_c0', 's183_c0', 's190_c0'], extent='related_joint_protocol_trigger_from_executed_fields', notes=[
    'Both reviewers locate actual failure of a combined phase/text sequence, despite differing press/repeat examples. Root retains the original Alt+Shift metadata row as base and the executed repeat2 donor.',
    'The bytes passed to XTermParser are Trigger, not Context. One composite missing grammar requirement contains two independently executed fields; record component/edit counts separately.',
    'A proposes key65 in the assembled sequence. Independent Kitty specification requires the unshifted key code97. The shift/text donor already executes97 with associated text65, so root normalizes the assembled input and records the third literal edit.',
    'Step118 writes tests; step119 reports92passed1xfailed, step18394passed1xfailed, and190104passed1xfailed. Phase and metadata checks therefore have actual execution receipts.',
    'Steps81/82 test regex probes with phase parsed after text. They are executed related observations with an incorrect combined interpretation, not a trusted correct-order joint oracle.',
    'Three logical source units across two test functions, two transferred components and one new ordering relation. The original metadata assertions remain; no new phase assertion is needed to detect the documented fallback-to-many-events bug.',
    'No assembled candidate has been run; keep grammar validation and blind discovery separate.'
])
