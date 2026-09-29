"""Register real test outcomes and source-before-mutation observations."""
from __future__ import annotations

from collections import defaultdict
from pathlib import Path
import json

from combination_testing.test_reports import _selected_test_name
from .checkpoint import read, digest
from .frontier import Frontier, fingerprint


def collect(execution, previous=None):
    execution = Path(execution)
    previous = previous or {}
    runs = read(execution/'runs.json')
    frontier = Frontier.restore(previous['frontier']) if previous.get('frontier') else Frontier()
    executed = set(previous.get('executed_candidate_ids', []))
    attempted = set(previous.get('attempted_candidate_ids', []))
    history = list(previous.get('results', []))
    parents = {row['candidate']['id']: row for row in previous.get('eligible_parents', [])}
    known_batches = list(previous.get('registered_batches', []))
    evidence_files = {str((execution/'runs.json').resolve()): digest(execution/'runs.json')}
    reports, candidates, events, outcomes = {}, {}, defaultdict(list), {}
    stage = execution/'stage.json'
    if stage.exists():
        accepted = Path(read(stage)['input'])/'accepted.json'
        if accepted.exists():
            candidates.update({row['id']: row for row in read(accepted)})
            attempted.update(key for key, row in candidates.items() if not row.get('is_source_profile'))
            evidence_files[str(accepted)] = digest(accepted)
    controls, source_profiles = {}, {}
    seen_traces = set()
    for row in runs:
        result_path = Path(row['result'])
        if str(result_path) not in reports:
            reports[str(result_path)] = read(result_path)
            evidence_files[str(result_path)] = digest(result_path)
            runtime = result_path.parent/'result.json'
            if runtime.exists():
                evidence_files[str(runtime)] = digest(runtime)
        report = reports[str(result_path)]
        matched = [test for test in report['tests'] if _selected_test_name(test['id'], set(row['test_ids']))]
        okay = bool(matched) and not report['errors'] and all(test['status'] == 'pass' for test in matched)
        if row['role'] == 'control':
            for identifier in row['test_ids']:
                controls[(row['manifest'], identifier)] = okay
            continue
        identifier = row['candidate_id']
        attempted.add(identifier)
        # A report of skip/collection failure alone is not a test-body execution.
        did_execute = any(test['status'] in {'pass', 'fail'} for test in matched)
        if did_execute:
            executed.add(identifier)
        outcomes[(row['manifest'], identifier)] = dict(
            executed=did_execute, statuses=[test['status'] for test in matched],
            report_errors=report['errors'], source_profile=row['role'] == 'source_profile')
        if row['role'] == 'source_profile':
            source_profiles[(row['manifest'], identifier)] = okay
        accepted = Path(row['manifest']).parent.parent/'accepted.json'
        if str(accepted) not in evidence_files:
            evidence_files[str(accepted)] = digest(accepted)
            candidates.update({candidate['id']: candidate for candidate in read(accepted)})
        trace = Path(row.get('trace', result_path.parent/'relation_trace.jsonl'))
        if trace.is_file() and str(trace) not in seen_traces:
            seen_traces.add(str(trace))
            evidence_files[str(trace)] = digest(trace)
            for line in trace.read_text().splitlines():
                if line.strip():
                    event = json.loads(line)
                    events[event['candidate_id']].append(event)
    identity = fingerprint(evidence_files)
    if identity in known_batches:
        return previous

    # Seed profiles really ran in a preceding process, and are registered first.
    # Repeated source profiles in different groups share source IDs/windows.
    ordered = sorted(candidates, key=lambda key: (not candidates[key].get('is_source_profile'), key))
    round_results = []
    measured_seeds = set()
    for identifier in ordered:
        candidate = candidates[identifier]
        contexts = [row for row in runs if row['candidate_id'] == identifier and row['role'] != 'control']
        if not contexts:
            continue
        result = frontier.observe(identifier, events[identifier])
        if candidate.get('is_source_profile') and result['measured_profiles']:
            measured_seeds.add(identifier)
        was_executed = any(outcomes[(row['manifest'], identifier)]['executed'] for row in contexts)
        valid_contexts = []
        for row in contexts:
            outcome = outcomes[(row['manifest'], identifier)]
            source_okay = all(controls.get((row['manifest'], key), False) for key in row['control_ids'])
            profiles_okay = all(source_profiles.get((row['manifest'], key), False)
                                for key in candidate.get('source_profile_ids', []))
            valid_contexts.append(outcome['executed'] and not outcome['report_errors'] and
                                  source_okay and profiles_okay and bool(row['control_ids']))
        eligible = any(valid_contexts) and not candidate.get('is_source_profile')
        result.update(executed=was_executed, parent_eligible=eligible,
                      is_source_profile=bool(candidate.get('is_source_profile')),
                      control_and_seed_valid=any(valid_contexts), event_count=len(events[identifier]),
                      profile_baseline_measured=bool(candidate.get('source_profile_ids')) and
                          all(key in measured_seeds for key in candidate.get('source_profile_ids', [])),
                      candidate_outcomes=[outcomes[(row['manifest'], identifier)] for row in contexts])
        if identifier in previous.get('executed_candidate_ids', []) and identifier in parents:
            result['already_registered_parent'] = True
        elif eligible:
            # Keep actual feedback, including no-profile execution, for the
            # separately labelled rotation control. Profile expansion gates it.
            parents[identifier] = dict(candidate=candidate, feedback=result)
        history.append(result)
        round_results.append(result)
    totals = defaultdict(int)
    elapsed = 0.0
    for path, report in reports.items():
        role = Path(path).parent.name
        for status, count in report['counts'].items():
            totals[role + '_' + status] += count
        totals['reported_test_outcomes'] += sum(report['counts'].values())
        totals['executed_test_outcomes'] += sum(report['counts'].get(status, 0) for status in ('pass', 'fail'))
        runtime = Path(path).parent/'result.json'
        if runtime.exists():
            elapsed += read(runtime).get('elapsed_seconds', 0.0)
            evidence_files[str(runtime)] = digest(runtime)
    known_batches.append(identity)
    rounds = [*previous.get('rounds', []), dict(execution=str(execution.resolve()), identity=identity,
               counters=dict(totals), elapsed_test_seconds=elapsed,
               new_generated_profiles=sum(len(row['new_profiles']) for row in round_results if not row['is_source_profile']),
               new_eligible_generated_profiles=sum(len(row['new_profiles']) for row in round_results
                   if row['parent_eligible'] and row['profile_baseline_measured']),
               generated_with_profiles=sum(bool(row['measured_profiles']) for row in round_results if not row['is_source_profile']),
               source_profiles_first=True, evidence_sha256=evidence_files)]
    return dict(version=1, frontier=frontier.snapshot(), results=history, current_results=round_results,
                executed_candidate_ids=sorted(executed), attempted_candidate_ids=sorted(attempted),
                eligible_parents=list(parents.values()), registered_batches=known_batches, rounds=rounds,
                measured_profile_count=len(frontier.profiles),
                unsupported_dynamic_languages=['go', 'typescript'],
                missing_trace_is_not_coverage=True)
