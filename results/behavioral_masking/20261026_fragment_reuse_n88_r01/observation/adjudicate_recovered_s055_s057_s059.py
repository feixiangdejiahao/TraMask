"""Preserved revisions after independent recovered-source inspection."""
import copy
from root_record_io import OBS, read, start, finish_revision

for cid, primary in [('S055', 'A'), ('S057', 'B'), ('S059', 'A')]:
    d = read(OBS / f'adjudicated/{cid}.json')
    proposed, reviews, raw = start(cid, primary)
    old_minimum = copy.deepcopy(d['minimal_assembly'])
    for key in ['required_factor_inventory', 'agent_base_units', 'missing_factors', 'minimal_assembly']:
        d[key] = copy.deepcopy(proposed[key])
    d['minimal_assembly']['new_external_primitive_knowledge'] = 0
    if cid == 'S055':
        recovery = OBS / f'source_recovery/{cid}/attempt_stock_A002/report.json'
        source = recovery.parent / 'original/files/v1/topdown/topdown_test.go'
        assert all(f['provenance_class'] == 'Exact Executed Fragment' for f in d['missing_factors'])
        actions = ['s54_c0', 's95_c0', 's131_c0']
        reason = 'Recovered stock trace assertions establish actually executed successful parent with body-nested failed child under negation.'
        extent = 'exact_nested_negation_and_entered_failure_components_with_retained_parent_check'
        d['minimal_assembly']['proposal'] = 'Combine original profiled successful-parent test, stock body-nested not-q structure, and historical95 non-index-pruned failing predicate. Retain original parent Evals1/Successes1 assertion; separately confirm child entry.'
        notes = [
            'The newly recovered TestTopDownEarlyExit row executes p containing not q, with q tracing and then failing. Its hard trace multiset requires p1, five q entries, and p2; generic negation syntax alone is not the evidence.',
            'Step131 runs unfiltered topdown with -count=1 and profile tag and reports a fresh PASS. The stock source matches original/checkpoint/CAS. Both reviewers now identify Exact executed nested-negation context.',
            'Keep95 as the separate entered-failure donor because54 equality predicate was index-pruned. Three source units, two transferred semantic conditions, zero newly invented ingredients. The profiled joint remains unexecuted.',
            'This supersedes the earlier claim that no nested entry occurred historically. It does not establish that the stock trace test checked the new profiler counter or that assembly succeeds on P/R.'
        ]
    elif cid == 'S057':
        recovery = OBS / f'source_recovery/{cid}/attempt_stock_A001/report.json'
        source = recovery.parent / 'original/files/crates/oxvg_optimiser/src/jobs/snapshots/oxvg_optimiser__jobs__collapse_groups__collapse_groups-9.snap'
        actions = ['s71_c0', 's265_c0', 's268_c0', 's330_c0', 's331_c0']
        reason = 'Restored exact stock snapshot9 establishes class-on-group ownership expectation in an actually executed donor.'
        extent = 'related_class_anchor_and_outside_base_ownership_check_components'
        d['minimal_assembly'].update(proposed_source_units=2, proposed_transferred_fragments=2, new_semantic_elements=1,
            proposal='Compose the original structural child selector with stock class-qualified group identity, and transfer the stock class-on-group ownership expectation. Preserve child matching; do not freeze an unrelated id on the group.')
        notes = [
            'Snapshot9 is the class fixture; snapshot13 is unrelated. The recovered expected SVG preserves outer class n and inner class i on their groups, while id b moves to the inner group. Thus id ownership must not be inferred from class ownership.',
            'The collapse_groups harness and snapshot are bound to the330→331 complete65PASS run. This is actual outside-base expected class ownership, stronger than the previously visible input and the original g/path assertion alone.',
            'Both missing factors remain Related because class-qualified structural-ancestor matching is newly composed. Count two source units and two semantic fragments from the stock donor, with one new joint relation; B one-fragment field bundles the two transfers.',
            'Retain root class-qualified primary and the original id-placement compatibility requirement. No full class-qualified ancestor witness or P/R result has been established.'
        ]
    else:
        recovery = OBS / f'source_recovery/{cid}/attempt_stock_A001/report.json'
        source = recovery.parent / 'original/files/error_test.go'
        actions = ['s190_c0', 's196_c0', 's208_c0', 's230_c0', 's244_c0']
        reason = 'Recovered TestErrors establishes executed DB.Open with fault-injecting filesystem; real-DB fault routing is no longer an absent external primitive.'
        extent = 'related_real_db_fault_injection_with_new_WAL_timing_and_wait_error_relations'
        d['minimal_assembly']['additional_baseline_obligation'] = old_minimum['additional_baseline_obligation']
        d['minimal_assembly']['proposal'] = 'Combine original WaitForDurability test with stock DB+errorfs setup, historical LogWriter Sync failure, and commit/callback error propagation. Restrict injection to WAL Sync after successful Open; retain the independent baseline-watermark qualification.'
        notes = [
            'TestErrors actually opens a DB using errorfs, performs writes/flush/compaction and checks injected errors including MANIFEST failures. The208→230 -count=1 run reports fresh root-package PASS; its aggregate failure from other packages is retained.',
            'This is an executed real-DB fault-injection primitive, not a proof of WAL-only Sync failure after Open. The required routing/timing and WaitForDurability error relation remain newly composed Related factors.',
            'Primary A now uses four units and three transferred fragments, with two new semantic relations and zero new external primitive. B independently confirms this as alternative error-latching evidence while retaining its different near-boundary notification proposal.',
            'Do not substitute MANIFEST failures for the focal WAL error. Original high>=seqNum+2 baseline remains unresolved on R and is not repaired by this source recovery. No execution-validated minimum or joint result is claimed.'
        ]
    finish_revision(d, raw, reason=reason, actions_checked=actions, notes=notes, extent=extent,
                    recovery_paths=[recovery, source])
