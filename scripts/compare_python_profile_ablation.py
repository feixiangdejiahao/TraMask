"""Read-only accounting for the preregistered Python profile/rotation ablation.

Raw failures and previously known material matches are not new semantic verdicts.
This script never imports generation, model or subject-runner code.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import sys
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from combination_testing.test_reports import _selected_test_name

ROLES = {'control': 0, 'source_profile': 1, 'generated': 2}


def read(path):
    return json.loads(Path(path).read_text())


def frozen(path):
    path = Path(path)
    return {'path': str(path.resolve()), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}


def suite_times(directory):
    xml = directory/'junit.xml'
    if not xml.exists():
        return None, None
    try:
        suites = ET.parse(xml).getroot().iter('testsuite')
        intervals = []
        for suite in suites:
            stamp = suite.get('timestamp')
            if stamp:
                start = datetime.fromisoformat(stamp.replace('Z', '+00:00'))
                if start.tzinfo is None:
                    start = start.replace(tzinfo=timezone.utc)
                intervals.append((start, start + timedelta(seconds=float(suite.get('time', 0)))))
        if intervals:
            return min(x[0] for x in intervals).isoformat(), max(x[1] for x in intervals).isoformat()
    except (ET.ParseError, ValueError):
        pass
    return None, None


def summarize_case(case_root, campaign_row):
    rounds, events, phases, inputs = [], [], [], []
    total_counts, elapsed_phases, execution_wall = Counter(), 0.0, 0.0
    body_ordinal, generated_ordinal, program_selected_before = 0, 0, 0
    for row in campaign_row.get('rounds', []):
        folder = case_root/f"round_{row['round']:03d}"
        selected_path, pool_path = folder/'prepared/candidates.json', folder/'prepared/source_pool.json'
        semantic_path, feedback_path = folder/'semantic/candidates.json', folder/'feedback.json'
        runs_path, receipt_path = folder/'executed/runs.json', folder/'executed/checkpoint.json'
        selected = read(selected_path)['candidates']
        source_pool = read(pool_path)['candidates']
        semantic = read(semantic_path)['candidates']
        feedback, runs = read(feedback_path), read(runs_path)
        feedback_rows = {item['candidate_id']: item for item in feedback.get('current_results', [])}
        execution_wall += read(receipt_path)['result'].get('wall_seconds', 0)
        inputs.extend(frozen(p) for p in (selected_path, pool_path, semantic_path, feedback_path, runs_path, receipt_path))
        candidate_map = {c['id']: c for c in semantic}
        program_ranks = {c['id']: rank for rank, c in enumerate(selected, 1)}
        semantic_ranks = {c['id']: rank for rank, c in enumerate(semantic, 1)}
        report_rows = defaultdict(list)
        for run in runs:
            report_rows[run['result']].append(run)
        controls = {}
        for run in runs:
            if run['role'] != 'control':
                continue
            report = read(run['result'])
            matched = [test for test in report['tests'] if _selected_test_name(test['id'], set(run['test_ids']))]
            okay = bool(matched) and not report.get('errors') and all(test['status'] == 'pass' for test in matched)
            for identifier in run['test_ids']:
                controls[(run['manifest'], identifier)] = okay
        report_order = sorted(report_rows, key=lambda p: (report_rows[p][0]['manifest'], ROLES[report_rows[p][0]['role']]))
        round_executed = []
        round_counts = Counter()
        for path in report_order:
            records = report_rows[path]
            role = records[0]['role']
            report_path = Path(path)
            report = read(report_path)
            runtime_path = report_path.parent/'result.json'
            runtime = read(runtime_path) if runtime_path.exists() else {}
            duration = runtime.get('elapsed_seconds', 0)
            start, end = suite_times(report_path.parent)
            elapsed_phases += duration
            inputs.append(frozen(report_path))
            if runtime_path.exists():
                inputs.append(frozen(runtime_path))
            xml = report_path.parent/'junit.xml'
            if xml.exists():
                inputs.append(frozen(xml))
            phases.append(dict(round=row['round'], role=role, path=path,
                               counts=report['counts'], report_errors=report.get('errors', []),
                               elapsed_seconds=duration, suite_start_utc=start, suite_end_utc=end,
                               timed_out=runtime.get('timed_out', False)))
            for status, count in report['counts'].items():
                total_counts[role+'_'+status] += count
                round_counts[role+'_'+status] += count
            # For Python, normalized testcase order preserves the JUnit order.
            for test in report['tests']:
                if test['status'] not in {'pass', 'fail'}:
                    continue
                matches = [run for run in records if _selected_test_name(test['id'], set(run['test_ids']))]
                body_ordinal += 1
                if role == 'generated':
                    generated_ordinal += 1
                identifier = matches[0]['candidate_id'] if len(matches) == 1 else None
                candidate = candidate_map.get(identifier, {})
                program_rank = program_ranks.get(identifier, program_ranks.get(candidate.get('static_parent_id')))
                control_ids = matches[0]['control_ids'] if len(matches) == 1 else []
                source_okay = bool(control_ids) and all(controls.get((matches[0]['manifest'], key), False) for key in control_ids)
                if role == 'generated' and identifier and identifier not in round_executed:
                    round_executed.append(identifier)
                events.append(dict(round=row['round'], role=role, id=identifier, test_id=test['id'],
                    status=test['status'], kind=test.get('kind'), report=path,
                    body_execution_ordinal=body_ordinal,
                    generated_execution_ordinal=generated_ordinal if role == 'generated' else None,
                    round_program_selection_rank=program_rank,
                    cumulative_program_selection_rank=program_selected_before+program_rank if program_rank is not None else None,
                    round_semantic_candidate_rank=semantic_ranks.get(identifier),
                    operator=candidate.get('operator', candidate.get('kind')),
                    is_extension=candidate.get('operator') == 'executed_parent_extension',
                    phase_elapsed_cumulative_upper_bound=round(elapsed_phases, 3),
                    phase_suite_end_utc_upper_bound=end,
                    source_control_qualified=source_okay,
                    source_and_seed_qualified=feedback_rows.get(identifier, {}).get('control_and_seed_valid', False),
                    report_errors=report.get('errors', [])))
        last = feedback['rounds'][-1]
        extension_parent_feedback = {}
        selected_ids = {candidate['id'] for candidate in selected}
        for candidate in source_pool:
            if candidate['id'] not in selected_ids or candidate.get('operator') != 'executed_parent_extension':
                continue
            parent = candidate.get('runtime_parent_id')
            actual = candidate.get('provenance', {}).get('composition', {}).get('runtime_parent_feedback', {})
            if actual.get('status') != 'runtime_observed' or not actual.get('measured_profiles'):
                category = 'no_measured_profile'
            elif actual.get('profile_baseline_measured') is False:
                category = 'baseline_not_measured'
            elif actual.get('retained') is not True:
                category = 'measured_not_retained'
            else:
                category = 'measured_retained'
            extension_parent_feedback[parent] = dict(category=category,
                strict_new_profile_count=len(actual.get('new_profiles', [])),
                measured_profile_count=len(actual.get('measured_profiles', [])))
        rounds.append(dict(round=row['round'], program_selected_ids=[c['id'] for c in selected],
            semantic_candidate_ids=[c['id'] for c in semantic], actually_executed_generated_ids=round_executed,
            extension_pool_ids=[c['id'] for c in source_pool if c.get('operator') == 'executed_parent_extension'],
            selected_extension_ids=[c['id'] for c in selected if c.get('operator') == 'executed_parent_extension'],
            executed_extension_ids=[identifier for identifier in round_executed
                                    if candidate_map[identifier].get('operator') == 'executed_parent_extension'],
            extension_parent_ids=sorted({c['runtime_parent_id'] for c in source_pool
                if c.get('operator') == 'executed_parent_extension' and 'runtime_parent_id' in c}),
            selected_extension_parent_feedback=extension_parent_feedback,
            eligible_parent_count=len(feedback.get('eligible_parents', [])),
            measured_profile_count=feedback.get('measured_profile_count'),
            new_generated_profiles=last.get('new_generated_profiles'),
            new_eligible_generated_profiles=last.get('new_eligible_generated_profiles'),
            generated_with_profiles=last.get('generated_with_profiles'),
            execution_counts=dict(round_counts), provider_calls=row['semantic']['provider_calls'],
            replay_revisions=row['semantic']['revised_count']))
        program_selected_before += len(selected)
    starts = [p['suite_start_utc'] for p in phases if p['suite_start_utc']]
    first_suite = min(starts) if starts else None
    for event in events:
        end = event['phase_suite_end_utc_upper_bound']
        event['seconds_from_first_suite_upper_bound'] = round((datetime.fromisoformat(end)-datetime.fromisoformat(first_suite)).total_seconds(), 3) if end and first_suite else None
    return dict(case=case_root.name, rounds=rounds, phase_reports=phases, execution_events=events,
        execution_counts=dict(total_counts), total_test_body_executions=body_ordinal,
        generated_test_body_executions=generated_ordinal, phase_elapsed_seconds=round(elapsed_phases, 3),
        source_control_qualified_generated_failures=sum(e['role'] == 'generated' and e['status'] == 'fail'
            and e['source_control_qualified'] and not e['report_errors'] for e in events),
        source_and_seed_qualified_generated_failures=sum(e['role'] == 'generated' and e['status'] == 'fail'
            and e['source_and_seed_qualified'] and not e['report_errors'] for e in events),
        execution_stage_wall_seconds=round(execution_wall, 3), first_suite_start_utc=first_suite,
        stopped_reason=campaign_row.get('stopped_reason'),
        provider_calls=sum(r['provider_calls'] for r in rounds),
        replay_revisions=sum(r['replay_revisions'] for r in rounds),
        evidence_files=list({item['path']: item for item in inputs}.values()))


def add_reachability(case, diagnostic):
    records = [r for r in diagnostic.get('matching_executions_for_review', [])
               if r['case'] == case['case'] and r.get('complete_signature_matches')]
    matches = []
    for record in records:
        events = [e for e in case['execution_events'] if e['role'] == 'generated'
                  and e['id'] == record['id'] and e['report'] == record['result']]
        for event in events:
            matches.append({**event, 'reference_id': record['reference_id'],
                            'interpretation': 'Previously confirmed complete material matched; fresh failure-cause/control review remains separate.'})
    matches.sort(key=lambda row: row['body_execution_ordinal'])
    case['known_material_execution_matches'] = matches
    case['first_known_material_execution'] = matches[0] if matches else None
    failed = [row for row in matches if row['status'] == 'fail' and not row['report_errors']]
    case['first_known_material_failure_pending_review'] = failed[0] if failed else None


def add_confirmations(case, review):
    confirmed = [row for row in review.get('fresh_evaluation', {}).get('deliveries', [])
                 if row['case'] == case['case'] and row.get('controlled_target_detection')]
    identifiers = {row['id'] for row in confirmed}
    events = [row for row in case['execution_events'] if row['role'] == 'generated'
              and row['id'] in identifiers and row['status'] == 'fail' and not row['report_errors']]
    if identifiers - {row['id'] for row in events}:
        raise ValueError('Independent verdict lacks a matching actual failure in this arm')
    case['independently_confirmed_target_ids'] = sorted(identifiers)
    case['first_confirmed_target_failure'] = events[0] if events else None


def compare(directory, reviews=None):
    protocol = read(directory/'protocol.json')
    launch_path = directory/'launch_metadata_v2.json'
    if not launch_path.exists():
        launch_path = directory/'launch_metadata.json'
    launch = read(launch_path)
    process_records = {row['arm']: row for row in launch['arms']}
    configurations = {arm: read(directory/arm/'configuration.json') for arm in ('profile', 'rotation')}
    left, right = configurations['profile'], configurations['rotation']
    differing = sorted(key for key in set(left)|set(right) if left.get(key) != right.get(key))
    if differing != ['strategy']:
        raise ValueError('Arms differ beyond strategy: '+str(differing))
    if left['cases'] != protocol['cases'] or left['algorithm_sha256'] != protocol['algorithm_sha256']:
        raise ValueError('Configuration differs from registered source/code/cases')
    expected = dict(rounds=protocol['fixed_budget']['rounds'], limit=protocol['fixed_budget']['program_candidates_per_round'],
                    pool=protocol['fixed_budget']['source_pool_budget'], max_edits=protocol['fixed_budget']['max_edits'],
                    group_size=protocol['fixed_budget']['group_size'], timeout=protocol['fixed_budget']['timeout_seconds'],
                    workers=1, include_baseline=True, oracle_mode='replay',
                    oracle_cache_sha256=protocol['oracle_cache']['sha256'], source_root=protocol['source_root'],
                    source_corpus_sha256={case: files['corpus.json'] for case, files in protocol['source_sha256'].items()})
    if any(left.get(key) != value for key, value in expected.items()):
        raise ValueError('Budget, source, or semantic mode differs from protocol')
    arms = {}
    for arm in ('profile', 'rotation'):
        rows = read(directory/arm/'campaign.json')
        if {row['case'] for row in rows} != set(protocol['cases']):
            raise ValueError('Every registered case must complete before comparison')
        for row in rows:
            if row.get('stopped_reason') == 'exhausted':
                exhaustion = Path(row['exhausted_prepare']).parent/'candidates.json'
                if read(exhaustion)['candidates']:
                    raise ValueError('Exhaustion did not have an empty selected set')
            elif len(row.get('rounds', [])) != left['rounds']:
                raise ValueError('Registered round budget not completed')
        cases = [summarize_case(directory/arm/row['case'], row) for row in rows]
        reachability = directory/(arm+'_reachability.json')
        if reachability.exists():
            diagnostic = read(reachability)
            for case in cases:
                add_reachability(case, diagnostic)
        review_path = (reviews or {}).get(arm)
        if review_path:
            review = read(review_path)
            if review.get('configuration_sha256') != frozen(directory/arm/'configuration.json')['sha256']:
                raise ValueError('Independent review belongs to a different campaign configuration')
            for case in cases:
                add_confirmations(case, review)
        counts = Counter()
        for case in cases:
            counts.update(case['execution_counts'])
        arms[arm] = dict(cases=cases, execution_counts=dict(counts),
            end_to_end_arm_wall_seconds=process_records[arm]['elapsed_wall_seconds'],
            total_test_body_executions=sum(c['total_test_body_executions'] for c in cases),
            generated_test_body_executions=sum(c['generated_test_body_executions'] for c in cases),
            source_control_qualified_generated_failures=sum(c['source_control_qualified_generated_failures'] for c in cases),
            source_and_seed_qualified_generated_failures=sum(c['source_and_seed_qualified_generated_failures'] for c in cases),
            phase_elapsed_seconds=round(sum(c['phase_elapsed_seconds'] for c in cases), 3),
            execution_stage_wall_seconds=round(sum(c['execution_stage_wall_seconds'] for c in cases), 3),
            provider_calls=sum(c['provider_calls'] for c in cases),
            independently_confirmed_cases=[c['case'] for c in cases if c.get('independently_confirmed_target_ids')],
            independent_review=frozen(review_path) if review_path else None,
            configuration=frozen(directory/arm/'configuration.json'), campaign=frozen(directory/arm/'campaign.json'))
    differences = []
    for name in protocol['cases']:
        a, b = [next(c for c in arms[arm]['cases'] if c['case'] == name) for arm in ('profile', 'rotation')]
        def flatten(case, key):
            return [value for row in case['rounds'] for value in row[key]]
        item = {'case': name}
        for key in ('program_selected_ids', 'actually_executed_generated_ids', 'extension_pool_ids',
                    'selected_extension_ids', 'executed_extension_ids'):
            x, y = flatten(a, key), flatten(b, key)
            item[key] = dict(same_order=x == y, same_set=set(x) == set(y),
                             profile_only=sorted(set(x)-set(y)), rotation_only=sorted(set(y)-set(x)))
        differences.append(item)
    return dict(created_utc=datetime.now(timezone.utc).isoformat(), protocol=frozen(directory/'protocol.json'),
        launch=frozen(launch_path),
        resource_override=frozen(directory/'resource_override_v2.json') if (directory/'resource_override_v2.json').exists() else None,
        evaluator=frozen(Path(__file__)), configuration_difference=differing, denominator=len(protocol['cases']),
        arms=arms, differences=differences,
        interpretation='Strategy-only ablation; zero fresh semantic calls. Target material reachability and raw failures require independent semantic/control review.',
        timing_limits='Per-target time is an upper bound from the containing JUnit suite end; it excludes construction before the first case suite. Execution-stage wall sums include Docker startup. Full arm process wall time comes from the bound launch metadata. Shared-host load and cache warming prevent a causal speed claim from one sequential pair.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('--input', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--profile-review', type=Path)
    parser.add_argument('--rotation-review', type=Path)
    args = parser.parse_args()
    result = compare(args.input, {'profile': args.profile_review, 'rotation': args.rotation_review})
    if args.output.exists():
        raise ValueError('Use a new comparison filename; old evidence is immutable')
    args.output.write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps({arm: {k: v for k, v in row.items() if k not in {'cases'}} for arm, row in result['arms'].items()}))
