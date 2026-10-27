"""Recovered executed language conversion changes availability, not joint success."""
import copy
from root_record_io import OBS, read, start, finish_revision

for cid, execution in [('S022', 's169_c0'), ('S023', 's112_c0')]:
    d = read(OBS / f'adjudicated/{cid}.json')
    proposed, reviews, raw = start(cid)
    assert all(r['missing_factors'][0]['provenance_class'] == 'Related Executed Components'
               for r in reviews.values())
    for key in ['required_factor_inventory', 'agent_base_units', 'missing_factors', 'minimal_assembly']:
        d[key] = copy.deepcopy(proposed[key])
    d['minimal_assembly']['new_external_primitive_knowledge'] = 0
    d['minimal_assembly']['proposal'] = reviews['A']['minimal_assembly']['assembly_execution']['proposal']
    recovery = OBS / f'source_recovery/{cid}/attempt_stock_A001/report.json'
    source = recovery.parent / 'original/files/builtin/builtin_test.go'
    notes = [
        'Recovered unchanged builtin/builtin_test.go executes string(5), string(5.5), and string("5.5") in TestBuiltin; its harness compiles/runs each expression and compares the direct returned value. This establishes a semantic conversion/observation donor, not merely assertion syntax.',
        'Both independent reviewers identify Related support for applying that ordinary conversion to a caught error. The full caught-error conversion relation remains new; do not upgrade it to an Exact historical joint witness.',
        'Count two logical units including the original catch test and the stock builtin test. No new external conversion primitive is needed. The original task-derived message expectation is retained.',
    ]
    if cid == 'S022':
        notes += ['Step169 explicitly runs builtin with -count=1 and reports fresh0.072s PASS. Keep the existing root-selected boom row162 and its host-format comparison; B numeric123 is a separate alternative. One new semantic operation application.']
        extent = 'related_executed_string_conversion_into_existing_caught_message_test'
    else:
        notes += ['Step112 reports fresh builtin0.023s PASS after a go-vet path error in the same shell. The vet error is retained and does not erase the subsequent package test output.',
                  'The original error-only Go cast must be replaced with a direct returned-string observation. Keep two semantic edits and the previous unresolved reference-baseline compatibility warning. This remains Trigger plus Check repair.']
        extent = 'related_conversion_and_direct_result_check_with_original_type_gate_unresolved'
    finish_revision(d, raw, reason='Recovered stock source plus actual historical execution establishes related conversion components previously classified absent.',
        actions_checked=[execution], notes=notes, extent=extent, recovery_paths=[recovery, source])
