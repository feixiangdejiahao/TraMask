"""Record bounded negative evidence and unresolved cached execution honestly."""
import copy
from root_record_io import OBS, read, start, finish_revision

d = read(OBS / 'adjudicated/S024.json')
proposed, reviews, raw = start('S024', 'B')
assert proposed['missing_factors'][0]['provenance_class'] is None
for key in ['required_factor_inventory', 'agent_base_units', 'missing_factors', 'minimal_assembly']:
    d[key] = copy.deepcopy(proposed[key])
d['workspace_visible_candidate_components'] = copy.deepcopy(reviews['B']['workspace_visible_candidate_components'])
d['minimal_assembly']['conditional_on_stock_execution'] = {
    'proposed_source_units': 2, 'proposed_transferred_fragments': 1,
    'description': 'A proposes the recovered TestBuiltin conversion donor, but actual trajectory execution of its body remains unresolved.',
    'counted_as_verified_executed_support': False}
recovery = OBS / 'source_recovery/S024/attempt_stock_A001/report.json'
finish_revision(d, raw, reason='Recovered conversion source exists, but available historical outputs do not establish a fresh body execution; replace broad Absent with unresolved.',
    actions_checked=['s109_c0', 's120_c0', 's201_c0'], extent='related_base_message_check_and_unresolved_stock_conversion_execution',
    recovery_paths=[recovery, recovery.parent / 'original/files/builtin/builtin_test.go'], notes=[
        'The same stock language-string rows are present as inS022/S023. S024109 full-suite output is truncated before builtin;120 and201 report successful whole-suite status but only tail output. Recovered201 builtin result is cached.',
        'A counts this as Related executed support. B separates visible source and cached confirmation from an identified body execution in this trajectory. Root adopts unresolved execution provenance, rather than Absent or verified Related.',
        'Keep the existing task/message expectation as Related. The known source provides a conditional two-unit assembly if execution correspondence is later recovered; the primary verified count remains one base unit with two new semantic edits.',
        'No new test run can retroactively prove what the Agent executed. No joint candidate outcome is added.'
    ])

d = read(OBS / 'adjudicated/S088.json')
_, reviews, raw = start('S088')
recovery = OBS / 'source_recovery/S088/attempt_stock_A001/report.json'
inventory = recovery.parent / 'test_source_search_inventory.json'
scan = read(inventory)
assert scan['scanned_file_count'] == 1007 and not scan['Info_or_Size_hits']
d['stock_source_coverage'] = {'scanned_test_sources': scan['scanned_file_count'],
    'Info_or_Size_hits': scan['Info_or_Size_hits'], 'scope': scan['scope'],
    'historical_executed_donor_found': False,
    'limit': 'Negative in the captured text test sources and recorded validation; not a claim about unrecorded history or all possible generated code.'}
finish_revision(d, raw, reason='Independent stock-source recovery and1007-file source scan confirm no additional Info/Size execution donor in the available evidence.',
    actions_checked=['s32_c0', 's173_c0', 's175_c0', 's217_c0'], extent='metadata_operation_and_size_decision_absent_in_bounded_executed_history',
    recovery_paths=[recovery, inventory], notes=[
        'Both reviewers inspected recovered stock sources and the1007-Go-test-source inventory. No Info or Size target call was found; host-harness ReadDir traversal does not execute interpreted embed metadata.',
        '175 selected packages without tests;217 selected TestEmbed only. These outputs cannot establish a missing metadata invocation.',
        'Retain the two bounded Absent missing factors. Standard embed source read32 exposes Size=len(data), so the oracle may be agent-visible without being an executed historical validation fragment. No new candidate was run.'
    ])
