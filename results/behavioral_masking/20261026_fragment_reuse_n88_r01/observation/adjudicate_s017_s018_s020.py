"""Distinguish executed bad behavior, namespace conventions, and patch versions."""
import copy
from root_record_io import start, finish

d, reviews, raw = start('S017', 'B')
d['missing_factors'][0]['role'] = 'Trigger'
for f in d['required_factor_inventory']:
    if f.get('factor_id') == d['missing_factors'][0]['factor_id']:
        f['role'] = 'Trigger'
d['minimal_assembly']['new_external_primitive_knowledge'] = 0
d['minimal_assembly']['proposal'] = 'Transfer exact nested HTML95 into the original flat-list test59/60; preserve its slice check and add the task-derived decision that b is inside the first outer li nested ul, and c remains the second outer li.'
d['minimal_assembly']['alternative_smaller_source_count'] = {'base': 'nested diagnostic95', 'source_units': 1, 'transferred_fragments': 0, 'new_semantic_elements': 1, 'description': 'Retain the already executed CLI input and add a structural ownership Check; this starts from a diagnostic, not the original asserting unit.', 'execution_validated': False}
d['historical_joint_witness']['reason'] = 'Nested bad behavior already prints in95, but no correct ownership decision is applied.'
finish(d, raw, actions_checked=['s59_c0', 's60_c0', 's95_c0', 's106_c0'], extent='exact_nested_stimulus_requires_new_structural_check', notes=[
    'The sole semantic official failure is nested-list ownership; the parent failing test is a duplicate wrapper. Historical95 already prints first outer li with empty nested ul, b promoted to outer li, and c leaked into body.',
    'Original59 checks only TypeSlice. Compilation fails59, the named unit passes60 after an unrelated helper fix, and106 freshly passes the HTML suite. The bad95 output still has an outer slice of length2, so neither the existing check nor merely adding length2 detects this witness.',
    'Nested markup changes target input, hence Trigger. Its exact historical execution is established. Correct nested ownership is a new task-derived Check; generic map navigation is not that semantic oracle.',
    'Select B counting one semantic ownership condition including observation navigation. A separates navigation and expected relation into two edits; retain that code-edit distinction without reporting two independent missing semantic conditions.',
    'The hard-base construction uses two units and one input transfer. Starting from95 directly needs one unit and a new Check. Neither source count is an execution-validated minimum or an automatic success.'
])

d, reviews, raw = start('S018', 'B')
d['minimal_assembly']['new_external_primitive_knowledge'] = 0
d['minimal_assembly']['proposal'] = 'Keep the authored repr/equality test95/96. Reuse module import and namespace assembly from51/54, then bind ns[datetime] to the module specifically at eval while retaining the class used to construct the original rule.'
d['oracle_availability']['status'] = 'module_namespace_convention_not_explicit_in_issue'
d['oracle_availability']['available_to_blind_system'] = None
d['historical_joint_witness']['reason'] = 'Earlier51 is the inverse mismatch: module-qualified repr evaluated under a class binding;53 repairs production repr for the class. No complete module-bound reconstruction witness is established.'
d['original_reference_control'] = {'status': 'not_executed', 'concern': 'Reference may emit datetime.datetime and reject the original class-bound baseline. Modified P fail/R pass would not by itself satisfy original P pass/R pass.'}
finish(d, raw, actions_checked=['s34_c0', 's51_c0', 's53_c0', 's54_c0', 's95_c0', 's96_c0'], extent='related_eval_namespace_components_with_convention_unresolved', compatibility='unresolved_namespace_contract_and_reference_baseline', notes=[
    'Step34 really executes module-bound datetime construction but not eval. Step51 imports the module as dt_mod and assembles ns, then globals overwrites datetime with the class; the resulting AttributeError is the opposite of the official module-not-callable failure.',
    'Step53 changes repr to bare datetime and prints three successful roundtrips under the class.54 reruns the diagnostic. Authored test95 contains the hard equality, and96 completes574passing tests.',
    'Select B: module import plus namespace assembly are executed components, but binding the module under datetime at this eval boundary is a new relation. Two logical units, two fragments from one donor, one Related Context factor.',
    'Issue promises reconstructable repr without fixing whether datetime denotes class or module. The Verifier establishes its module convention; that alone does not settle the independent contract boundary. Preserve the uncertainty explicitly.',
    'The separate custom-zone serialization failure is not addressed. No fresh candidate execution, no qualified Context-recoverable claim.'
])

d, reviews, raw = start('S020')
check = d['missing_factors'][1]
check['provenance_class'] = 'Related Executed Components'
check.pop('coverage_for_absent', None)
check['source_fragments'] = copy.deepcopy(reviews['B']['missing_factors'][0]['source_fragments'])
for f in check['source_fragments']:
    f['source_unit_id'] = 'annotated_openapi158'
check['derived_semantics'] = 'Actual printed success metadata145 and158 contains text/event-stream and EventA/B references. Turning this into a hard decision and applying it to endpoint-only marking is a new relation, not absent semantic content.'
for f in d['required_factor_inventory']:
    if f.get('missing_factor_id') == check['factor_id']:
        f['history_provenance'] = check['provenance_class']
d['oracle_availability']['historical_check_provenance'] = 'Related Executed Components'
d['minimal_assembly'].update(proposed_source_units=2, proposed_transferred_fragments=2, new_semantic_elements=1, new_external_primitive_knowledge=0,
    proposal='Use annotated OpenAPI diagnostic145/158, remove withSSE from the success union using the executed endpoint-only setup170/180/181, and assert the successful metadata shape printed145/158. Keep response200 distinct from400.')
d['historical_joint_witness']['reason'] = 'Correct annotated metadata is printed145/158 but never asserted. Unannotated SSE endpoint runtime is tested separately.'
d['historical_unit_aliases'] = {'annotated_openapi158': ['same scratchpad/sse_openapi.ts logical script executed145,146,158'], 'cardinality_note': 'Earlier output and later script versions are one unit; adding the endpoint-only runtime donor makes two, not three.'}
finish(d, raw, actions_checked=['s145_c0', 's146_c0', 's158_c0', 's170_c0', 's180_c0', 's181_c0', 's207_c0', 's215_c0', 's229_c0'], extent='exact_endpoint_setup_and_related_metadata_check_require_joint_transfer', notes=[
    'B selects the wrong annotated metadata printed146, but158 fixes symbol-key annotation preservation and reruns the same script: response200 is again text/event-stream with EventA/B anyOf, while400 is application/json. Thus an assertion on unchanged146 input is not evidence of detecting the final patch bug.',
    'Select A final-version alignment: transfer endpoint-only SSE marking without withSSE success annotation into the OpenAPI script. The unannotated endpoint is authored170 and its file actually completes23tests at181 after launch180.',
    'Root revises A Check provenance from Absent to Related: the correct success metadata is already printed145/158. It is not a historical hard assertion, but its exact semantic content supplies more than generic assertion syntax.',
    'Count two logical units: the OpenAPI script across versions and the runtime endpoint test. One setup fragment and one same-unit output-to-decision fragment; one new semantic joint decision, no new external primitive.',
    'The two official OpenAPI failures both first encounter absent SSE content; do not assume an independent union construction defect. fromStream bytes and plain-value handler failures remain separate.',
    'Scratchpad deletion207 does not erase historical evidence. Later215/229 passing suites are not a rerun of this script. No joint candidate execution is claimed.'
])
