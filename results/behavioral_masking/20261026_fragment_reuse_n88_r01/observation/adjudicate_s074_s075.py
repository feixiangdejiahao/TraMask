"""Explicit root decisions from independently reviewed source and raw actions."""
import copy
from root_record_io import start, finish

d, reviews, raw = start('S074')
d['minimal_assembly']['new_external_primitive_knowledge'] = 0
finish(d, raw, actions_checked=['s110_c0', 's125_c0'],
    extent='exact_clone_context_transfer_into_existing_distinct_shared_local_sibling_test', notes=[
        {'topic': 'independent agreement', 'resolution': 'Both identify the already executed inc/get sibling pair over one factory-local n and a separate CloneIsolation unit.110 prints named PASS for both despite a different AddTransfer failure;125 again reports named PASS and final packagePASS.'},
        {'topic': 'single context transfer', 'resolution': 'Insert c=c.Clone() after the original in-script out==2 assertion and before retrieving both inc/get Go callables. Clone captures n2, so the same increment then get should return3; preserve the entire original script, both checks and error handling.'},
        {'topic': 'what is already historical', 'resolution': 'The sibling-local graph and read-after-write oracle are complete in the base. The donor supplies cloning a compiled instance with mutated capture. Two source units, one exact transferred Context factor, zero new semantic ingredients; no joint execution is claimed.'},
        {'topic': 'scope', 'resolution': 'This is the known T13-related trajectory, not an independent fresh discovery. The actual Verifier clone graph returns10 after sibling increment11; another returned-composite failure is retained as a separate manifestation.'}])

d, reviews, raw = start('S075', 'B')
d['alternative_A_base'] = {k: copy.deepcopy(reviews['A'][k]) for k in
    ['agent_base_units', 'missing_factors', 'minimal_assembly']}
for f in d['missing_factors'] + d['required_factor_inventory']:
    if f.get('role') == 'Context' and ('undefined' in f.get('semantic_condition', '').lower()):
        f['role'] = 'Trigger'
        f['root_role_basis'] = 'Explicit source-map value is a target destructuring input.'
d['minimal_assembly']['new_external_primitive_knowledge'] = 0
d['historical_joint_witness'].update(trigger_and_wrong_effect_observed=True,
    action='s174_c0', observation='50',
    reason='The exact present-undefined/default50 operation ran, but the probe printed its wrong result without a rejecting assertion.')
finish(d, raw, actions_checked=['s148_c0', 's150_c0', 's174_c0', 's225_c0'],
    extent='exact_present_undefined_input_observed_but_correct_map_default_Check_requires_new_relation', notes=[
        {'topic': 'base distinction', 'resolution': 'A selects missing-key row{}→50; B selects existing-key row{x:2}→2 in the same148 map test. Root keeps B primary: source2→undefined and expected2→UndefinedValue. A equivalent alternative remains separately recorded; do not conflate their original expected values.'},
        {'topic': 'actual joint input already ran', 'resolution': '174 writes/runs f31.tengo containing{x:a=50}:={x:undefined}, prints50. This is the actual wrong behavior already visible in history, but not a complete asserted witness. The official map-default failure independently confirms the same missing-versus-present mistake.'},
        {'topic': 'Related Check', 'resolution': 'The base already demonstrates that an existing value suppresses default; a separate array test observes missing-position UndefinedValue. Together with Issue only-missing semantics they support the new expected undefined. Neither the printing probe nor a generic assertion helper supplies the full correct map-default oracle.'},
        {'topic': 'execution and roles', 'resolution': '150 repairs unrelated parse-test helpers;225 uncached root package passes in1.246s. Changing the literal source value is a Trigger edit, with a separate Check change. Three logical source units, two transferred ingredients and one new expected relation remain proposed.'}])
