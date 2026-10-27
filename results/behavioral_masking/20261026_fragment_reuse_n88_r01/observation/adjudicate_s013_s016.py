"""Explicit source adjudications; preserve alternative focal failures separately."""
from root_record_io import start, finish


d, reviews, raw = start('S013')
d['minimal_assembly']['new_external_primitive_knowledge'] = 0
d['minimal_assembly']['proposal'] = 'Keep the actually executed invalid TypedDict probe162; add the required-field/no-fallback value-is-None Check from dict_atomic74/207. Preserve its input and partial_structure operation.'
d['historical_joint_witness']['reason'] = 'Probe162 already prints the invalid raw mapping, but does not assert that no structured value can be returned.'
finish(d, raw, actions_checked=['s74_c0', 's162_c0', 's207_c0'], extent='exact_failing_stimulus_with_related_required_field_check', notes=[
    'The sole official failure is required_field_fails: invalid required integer a remains in r.value instead of yielding None. Agent probe162 actually reaches the same TypedDict behavior and prints the raw invalid mapping.',
    'The required attrs collection test authored74 and executed207 asserts r.value is None for an invalid required field. Its 25-test run passes. This supplies a related semantic rule, not an exact historical TypedDict oracle.',
    'Select A: two logical units, one transferred Check, one new cross-record-kind application, no new external primitive. The task explicitly supports TypedDict and specifies required fields without defaults.',
    'B instead transfers the TypedDict representation into the attrs atomic test. That preserves the nested invalid value but changes the schema argument to the target API; it must not be called an unchanged-input Context edit. Preserve it as a distinct unexecuted alternative.',
    'Do not transfer the separate historical TypedDict expectation that missing required fields still yield a partial dictionary. No assembled P/R execution has occurred.'
])

d, reviews, raw = start('S014', 'B')
d['minimal_assembly']['new_external_primitive_knowledge'] = 0
d['minimal_assembly']['proposal'] = 'In the original new-fetch-aborts-previous-signal test, resolve the initial promise and establish completed application before typing the next search. Reuse resolution and completion observations from the executed minimum-duration test; keep debounce10 and the original two-signal/aborted assertion.'
d['historical_joint_witness']['reason'] = 'Pending-request abortion and completed-request application were tested separately; the selected completed-before-replacement signal Check was not.'
d['fragment_timing_requirements'] = {'state': 'initial fetch has fully applied and completed cleanup before next search', 'one_microtask_sufficiency': 'not established by source inspection', 'excluded_automatic_transfers': ['cacheResults option', 'loadingMinDuration100'], 'execution_status': 'unvalidated'}
finish(d, raw, actions_checked=['s53_c0', 's58_c0', 's66_c0', 's68_c0', 's149_c0'], extent='related_completed_request_context_requires_new_temporal_joint_relation', notes=[
    'The original abort test never resolves its first request. The minimum-duration test actually resolves a request and observes loading false and applied options. Both named tests pass in53/58 even while other tests fail;149 runs the two core files with42passes.',
    'A also identifies the cache test66/68, with22tests passing after the cache expectation fix. Resolution and a microtask flush are real executed fragments, but a single await is not yet proof that the base implementation completed cleanup before replacement.',
    'Select B: two source units, two fragments from the same donor, one Related Context factor and one new completed-before-next-signal relation. The donor loading delay and caching mode are not part of the required transfer.',
    'The issue says starting a new fetch must abort the previous signal; its in-flight qualifier describes cleanup separately. The selected oracle is supported, while exact scheduling remains to be established by execution.',
    'Keep the retry error-visibility failure and six snapshot regressions separate. This proposal has not been executed on P/R.'
])

d, reviews, raw = start('S015', 'B')
d['minimal_assembly']['new_external_primitive_knowledge'] = 0
d['minimal_assembly']['proposal'] = 'In the original layered-background expansion test, replace only the expected background-color transparent,red with red. Preserve the layered shorthand input and all seven other expected fields.'
d['historical_joint_witness']['reason'] = 'Single-layer scalar color is observed in54; multi-layer tests85/86/188 encode the incorrect color list. No correct joint assertion is present.'
finish(d, raw, actions_checked=['s54_c0', 's85_c0', 's86_c0', 's188_c0'], extent='related_scalar_color_check_transfer_into_existing_layered_stimulus', notes=[
    'Step54 executes single-layer red expansion/compression with scalar background-color and prints the incorrect multi-layer color representation separately. Step85 writes assertions;86 executes26passing tests and188 executes28passing tests including the selected layered units.',
    'Select B expansion: two units, one Related Check transfer, one new application of the scalar final-layer rule, no new primitive. The task explicitly makes color the final-layer-only exception.',
    'A offers a distinct compression candidate: change the longhand input color list to scalar red and retain the canonical shorthand assertion. That edit changes the API argument and is Trigger, not Context.',
    'All three official failures concern this family, but the selected expansion proposal is not assumed to repair compression. A roundtrip through two components sharing the same wrong representation is not an independent oracle.',
    'The whole historical file contains other incorrect expectations; any named-unit scope must be fixed before execution and kept identical on P/R. No candidate has been run.'
])

d, reviews, raw = start('S016', 'B')
d['minimal_assembly']['new_external_primitive_knowledge'] = 0
d['minimal_assembly']['proposal'] = 'Keep the raw-script input and correctly escaped script-content expectation from45; add only body:"" to the expected normalized document, transferring the complete-document shape rule from the orphan-p test.'
d['historical_joint_witness']['reason'] = 'The original raw-script test asserts a head-only result. Other inputs assert both normalized head and body, but the rule is not applied to head-owned content.'
finish(d, raw, actions_checked=['s44_c0', 's45_c0', 's109_c0'], extent='related_normalization_check_transfer_into_existing_head_only_input', notes=[
    'The task explicitly requires both head and body even when absent. B selects a normalization failure, which is distinct from the nested-list failure selected by A.',
    'Step44 raw-script execution fails on JSON escaping;45 repairs escaping and freshly passes both the raw-text and normalization tests.109 cached output only corroborates this earlier execution.',
    'The raw-script expected object still omits body, while the orphan-p test expects head:"" and a body. Transfer that normalization rule, preserving the exact raw-script content and escaping.',
    'Two units, one Related Check fragment and one new head-owned-content application; no new external primitive. This is assertion repair, not pure Context repair.',
    'A proposes new nested-list input plus a new ownership oracle. Its input topology is Trigger and its absent nested donor must not be merged into the normalization proposal. No assembled execution is claimed.'
])
