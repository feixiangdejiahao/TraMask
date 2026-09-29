"""Independent continuation ledger: inherited witnesses are not fresh pipeline runs.

Only reads existing artifacts. Reuses frozen named-test and semantic checks;
never imports generation or provider code. A campaign qualifies separately from
witness correctness and requires cited independent automatic-provenance review.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
from types import SimpleNamespace

from evaluate_relation_search import CASES, evaluate, read, write_new
from evaluate_relational_gap import digest, freeze_file, verify_file, reviewed, matches_runtime, runtime_tests

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'results/relation_search_20260929/evaluation'
OLD = ROOT / 'results/relation_search_20260928/evaluation'


def initialize(args):
    old = read(OLD/'checkpoint_08_evaluation.json')
    assert old['denominator'] == 17
    for record in old['inputs'] + old['evidence_files']:
        verify_file(record)
    registry = {row['id']: row for row in read(ROOT/'data/relational_gap_v1/registry.json')}
    cases = []
    for case in CASES:
        record = registry[case]
        witnesses = [r for r in old['deliveries'] if r['case'] == case and r['controlled_target_detection']]
        cases.append({'case': case, 'image': record['image'], 'base_commit': record['base_commit'],
                      'candidate_patch': freeze_file(Path(record['candidate_patch'])),
                      'source_corpus': freeze_file(ROOT/f'results/relational_gap_20260928/batch7/{case}/corpus.json'),
                      'inherited_witnesses': [{'id': r['id'], 'origin': r['origin']} for r in witnesses],
                      'historical_axis': 'previously_executed_relation' if case == 'N06' else None})
    frozen = [freeze_file(OLD/'checkpoint_08_evaluation.json'),
              freeze_file(OLD/'checkpoint_08_deliveries.json'),
              freeze_file(OLD/'checkpoint_08_reviews.json'),
              freeze_file(ROOT/'scripts/evaluate_relation_search.py'),
              freeze_file(ROOT/'scripts/evaluate_relational_gap.py')]
    ledger = {'round': 'relation_search_20260929', 'denominator': 17,
              'start_utc': '2026-09-29T03:12:36Z', 'deadline_utc': '2026-09-29T08:12:36Z',
              'baseline_commit': '254ca6111340728a256807c60121b551ae00329c',
              'scope': '17 development trials; full corpus means each registered provided corpus, not every test in every possible repository.',
              'baseline': {'detected_cases': [r['case'] for r in old['cases'] if r['controlled_target_detection']],
                           'frozen_files': frozen}, 'cases': cases}
    write_new(args.ledger, ledger)
    write_new(args.deliveries, [])
    write_new(args.reviews, [])
    return {'start_utc': ledger['start_utc'], 'deadline_utc': ledger['deadline_utc'], 'inherited': 11, 'denominator': 17}


def _artifact(value):
    """Accept coordinator paths or a prior evaluator's frozen file records."""
    record = freeze_file(Path(value)) if isinstance(value, (str, Path)) else value
    verify_file(record)
    return record


def _manifest(path, evidence):
    record = _artifact(path)
    evidence.append(record)
    value = read(record['path'])
    for relative, checksum in value.get('files_sha256', {}).items():
        child = {'path': str(Path(record['path']).parent/relative), 'sha256': checksum}
        verify_file(child)
        evidence.append(child)
    return value


def _same_code(actual, expected):
    return bool(actual) and all(expected.get(path) == checksum for path, checksum in actual.items())


def _path(value):
    return str(Path(value).resolve())


def named_outcomes(runs):
    """Failures are execution inventory; semantic review remains separate."""
    reports, outcomes = {}, {}
    for row in runs:
        if row.get('role') != 'generated':
            continue
        path = Path(row['result'])
        if path not in reports:
            tests, errors, used = runtime_tests(path)
            errors = sorted(set(errors) | set(read(path).get('errors', [])))
            reports[path] = tests, errors, used
        tests, errors, _ = reports[path]
        requested = row.get('test_ids', [])
        selected = [test for test in tests if any(matches_runtime(test['id'], name) for name in requested)]
        missing = not requested or any(not any(matches_runtime(test['id'], name) for test in tests) for name in requested)
        status = ('execution_error' if errors else 'not_observed' if missing else
                  'failed' if any(test['status'] == 'fail' for test in selected) else
                  'passed' if selected and all(test['status'] == 'pass' for test in selected) else 'other')
        outcomes.setdefault(row['candidate_id'], set()).add(status)
    return outcomes


def verify_multiround_campaign(campaign, ledger, campaign_path):
    """Check the coordinator's actual stage arguments, not a claimed config SHA."""
    root = Path(campaign_path).resolve().parent
    configuration_record = freeze_file(root/'configuration.json')
    configuration = read(configuration_record['path'])
    expected = {row['case']: row for row in ledger['cases']}
    code = configuration.get('algorithm_sha256', {})
    global_evidence = [configuration_record]
    code_ok = bool(code)
    for relative, checksum in code.items():
        record = {'path': str(root/'algorithm_snapshot'/relative), 'sha256': checksum}
        if not Path(record['path']).is_file():
            code_ok = False
        else:
            verify_file(record)
            global_evidence.append(record)
    rows = {}
    for case_row in campaign:
        case = case_row['case']
        if case not in CASES or case in rows:
            raise ValueError('Campaign case must occur once within fixed17')
        evidence = list(global_evidence)
        source = _artifact(case_row['source_corpus'])
        evidence.append(source)
        case_config_record = _artifact(case_row['execution_configuration'])
        evidence.append(case_config_record)
        case_config = read(case_config_record['path'])
        source_directory = str(Path(source['path']).resolve().parent)
        config_ok = ({key: value for key, value in case_config.items() if key not in {'case', 'source'}} == configuration
                     and case_config.get('case') == case and _path(case_config.get('source', '.')) == source_directory
                     and case in configuration.get('cases', [])
                     and len(case_row['rounds']) <= configuration['rounds'])
        source_ok = (source['sha256'] == expected[case]['source_corpus']['sha256']
                     and source['sha256'] == configuration.get('source_corpus_sha256', {}).get(case)
                     and source_directory == _path(Path(configuration.get('source_root', '.'))/case))
        rounds, selected, executed, reports, indexes, outcomes = [], set(), set(), {}, [], {}
        previous_feedback = None
        for index, round_row in enumerate(case_row['rounds']):
            if round_row['round'] != index:
                raise ValueError('Campaign rounds must be consecutive and start at zero')
            program_record = _artifact(round_row['program_prepare_manifest'])
            semantic_record = _artifact(round_row['prepare_manifest'])
            candidates_record = _artifact(round_row['candidates'])
            runs_record = _artifact(round_row['runs_index'])
            evidence.extend([program_record, semantic_record, candidates_record, runs_record])
            program = _manifest(program_record, evidence)
            semantic = _manifest(semantic_record, evidence)
            program_dir, semantic_dir, execution_dir = (Path(program_record['path']).parent,
                                                        Path(semantic_record['path']).parent,
                                                        Path(runs_record['path']).parent)
            stage = _manifest(program_dir/'stage.json', evidence)
            semantic_stage = _manifest(semantic_dir/'stage.json', evidence)
            execution_stage = _manifest(execution_dir/'stage.json', evidence)
            emission_dir = Path(execution_stage['input'])
            emission_stage = _manifest(emission_dir/'stage.json', evidence)
            receipt = _manifest(execution_dir/'checkpoint.json', evidence)
            for relative, checksum in program.get('algorithm_sha256', {}).items():
                record = {'path': str(program_dir/'algorithm_snapshot'/relative), 'sha256': checksum}
                verify_file(record)
                evidence.append(record)
            round_config_ok = (all(stage.get(key) == configuration.get(key) for key in
                                   ('strategy', 'limit', 'pool', 'max_edits', 'include_baseline', 'representations_only'))
                               and stage.get('global_configuration_sha256') == configuration_record['sha256']
                               and _path(stage.get('source', '.')) == source_directory
                               and stage.get('previous_sha256') == previous_feedback
                               and semantic_stage.get('mode') == configuration.get('oracle_mode')
                               and semantic_stage.get('budget') == configuration.get('semantic_budget')
                               and semantic_stage.get('per_request') == configuration.get('per_request')
                               and semantic_stage.get('model_workers') == configuration.get('model_workers')
                               and semantic_stage.get('cache_sha256') == configuration.get('oracle_cache_sha256')
                               and emission_stage.get('group_size') == configuration.get('group_size')
                               and emission_stage.get('timeout') == configuration.get('timeout')
                               and execution_stage.get('workers') == configuration.get('workers'))
            round_code_ok = (code_ok and _same_code(program.get('algorithm_sha256', {}), code)
                             and stage.get('algorithm_sha256') == program.get('algorithm_sha256')
                             and semantic_stage.get('code_sha256') == code
                             and _same_code(emission_stage.get('algorithm_sha256', {}), code)
                             and execution_stage.get('runner_sha256') == code.get('scripts/execute_relation_search.py'))
            round_source_ok = (stage.get('source_sha256', {}).get('corpus.json') == source['sha256']
                               and program.get('source_identity', {}).get('corpus.json') == source['sha256']
                               and program.get('files_sha256', {}).get('corpus.json') == source['sha256']
                               and semantic.get('files_sha256', {}).get('corpus.json') == source['sha256'])
            chain_ok = (_path(semantic.get('source_prepare', '.')) == _path(program_record['path'])
                        and _path(semantic_stage.get('input', '.')) == _path(program_dir)
                        and semantic_stage.get('input_sha256') == program_record['sha256']
                        and _path(emission_stage.get('input', '.')) == _path(semantic_dir)
                        and emission_stage.get('input_sha256') == semantic_record['sha256'])
            candidates = read(candidates_record['path'])
            candidates = candidates['candidates'] if isinstance(candidates, dict) else candidates
            ids = {row['id'] for row in candidates}
            candidates_ok = (semantic.get('files_sha256', {}).get('candidates.json') == candidates_record['sha256']
                             and len(ids) == len(candidates))
            program_candidates = read(program_dir/'candidates.json')['candidates']
            candidates_ok = candidates_ok and len(program_candidates) <= configuration['limit']
            runs = read(runs_record['path'])
            runs = runs['runs'] if isinstance(runs, dict) else runs
            for identifier, statuses in named_outcomes(runs).items():
                outcomes.setdefault(identifier, set()).update(statuses)
            run_ids = {row['candidate_id'] for row in runs if row.get('role') == 'generated'}
            for row in runs:
                if row.get('role') == 'generated':
                    reports.setdefault(row['candidate_id'], set()).add(_path(row['result']))
            selected |= ids
            executed |= run_ids
            indexes.append(runs_record['path'])
            # Receipt binds actual reports and emitted manifests; failed tests
            # are completed execution, while missing/foreign indexes are not.
            execution_ok = (receipt.get('files_sha256', {}).get('runs.json') == runs_record['sha256']
                            and all(row.get('case') == case for row in runs)
                            and run_ids <= ids)
            for manifest, checksum in execution_stage.get('artifacts_sha256', {}).items():
                record = {'path': str(Path(manifest)/'manifest.json'), 'sha256': checksum}
                verify_file(record)
                evidence.append(record)
                if _path(read(record['path']).get('original_input', '.')) != _path(semantic_dir):
                    chain_ok = False
            feedback_file = execution_dir.parent/'feedback.json'
            evidence.append(freeze_file(feedback_file))
            previous_feedback = digest(feedback_file)
            model_result = read(semantic_dir/'semantic_result.json')
            rounds.append({'round': index, 'scope_verified': all((round_config_ok, round_code_ok, round_source_ok, chain_ok, candidates_ok, execution_ok)),
                           'configuration_matches': round_config_ok, 'algorithm_snapshot_matches': round_code_ok,
                           'source_corpus_matches': round_source_ok, 'artifact_chain_matches': chain_ok,
                           'selected_candidates_match': candidates_ok, 'execution_index_matches': execution_ok,
                           'selected_count': len(ids), 'indexed_generated_count': len(run_ids),
                           'provider_calls': model_result.get('provider_calls', 0),
                           'semantic_selected_count': len(model_result.get('selected_ids', []))})
        complete = len(rounds) == configuration['rounds']
        exhausted_ok = False
        if case_row.get('stopped_reason') == 'exhausted':
            exhaustion = _artifact(case_row.get('exhausted_prepare_manifest', case_row.get('exhausted_prepare')))
            evidence.append(exhaustion)
            exhaustion_directory = Path(exhaustion['path']).parent
            exhausted_manifest = _manifest(exhaustion, evidence)
            exhausted_stage = _manifest(exhaustion_directory/'stage.json', evidence)
            empty_candidates = exhaustion_directory/'candidates.json'
            evidence.append(freeze_file(empty_candidates))
            exhausted_ok = (not read(empty_candidates)['candidates']
                            and exhausted_stage.get('global_configuration_sha256') == configuration_record['sha256']
                            and exhausted_stage.get('previous_sha256') == previous_feedback
                            and exhausted_stage.get('source_sha256', {}).get('corpus.json') == source['sha256']
                            and _same_code(exhausted_manifest.get('algorithm_sha256', {}), code)
                            and all(exhausted_stage.get(key) == configuration.get(key) for key in
                                    ('strategy', 'limit', 'pool', 'max_edits', 'include_baseline', 'representations_only')))
            complete = exhausted_ok
        rows[case] = {'scope_verified': config_ok and source_ok and code_ok and (bool(rounds) or exhausted_ok) and all(row['scope_verified'] for row in rounds),
                      'configuration_matches': config_ok, 'source_corpus_matches': source_ok,
                      'algorithm_snapshot_matches': code_ok, 'rounds': rounds,
                      'selected_ids': selected, 'indexed_generated_ids': executed,
                      'generated_reports': reports, 'runs_indexes': indexes, 'complete': complete,
                      'oracle_mode': configuration.get('oracle_mode', 'unspecified'),
                      'selected_count': len(selected), 'indexed_generated_count': len(executed),
                      'provider_calls': sum(row['provider_calls'] for row in rounds),
                      'semantic_selected_count': sum(row['semantic_selected_count'] for row in rounds),
                      'named_outcome_counts': {status: sum(status in values for values in outcomes.values())
                                               for status in ('passed', 'failed', 'not_observed', 'execution_error', 'other')},
                      'named_failed_ids': {identifier for identifier, statuses in outcomes.items() if 'failed' in statuses},
                      'evidence_files': list({record['path']: record for record in evidence}.values())}
    return rows, configuration_record['sha256']


def verify_campaign(campaign, ledger, campaign_path=None):
    """Verify identity and source scope; independent review supplies automation judgment."""
    if campaign is None:
        return {}, None
    if isinstance(campaign, list):
        if campaign_path is None:
            raise ValueError('The coordinator campaign path locates its global configuration')
        return verify_multiround_campaign(campaign, ledger, campaign_path)
    verify_file(campaign['configuration'])
    configuration_sha = campaign['configuration']['sha256']
    code = campaign['algorithm_files']
    for record in code:
        verify_file(record)
    code_hashes = {record.get('algorithm_path', record['path']): record['sha256'] for record in code}
    rows = {}
    expected = {r['case']: r for r in ledger['cases']}
    for row in campaign['cases']:
        case = row['case']
        if case not in CASES or case in rows:
            raise ValueError('Campaign case must occur once within fixed17')
        for name in ('source_corpus', 'prepare_manifest', 'candidates', 'runs_index'):
            verify_file(row[name])
        prepared = read(row['prepare_manifest']['path'])
        candidates = read(row['candidates']['path'])
        candidates = candidates['candidates'] if isinstance(candidates, dict) else candidates
        ids = {c['id'] for c in candidates}
        runs = read(row['runs_index']['path'])
        runs = runs['runs'] if isinstance(runs, dict) else runs
        executed_ids = {r['candidate_id'] for r in runs if r.get('role') == 'generated'}
        prepared_code = prepared.get('algorithm_sha256', {})
        same_code = bool(code_hashes) and all(prepared_code.get(p) == sha for p, sha in code_hashes.items())
        input_hashes = prepared.get('files_sha256', {})
        source_ok = (row['source_corpus']['sha256'] == expected[case]['source_corpus']['sha256']
                     and input_hashes.get('corpus.json') == row['source_corpus']['sha256'])
        candidates_ok = input_hashes.get('candidates.json') == row['candidates']['sha256']
        config_ok = row.get('configuration_sha256') == configuration_sha
        rows[case] = {'scope_verified': source_ok and candidates_ok and config_ok and same_code,
                      'source_corpus_matches': source_ok, 'selected_candidates_match': candidates_ok, 'configuration_matches': config_ok,
                      'algorithm_snapshot_matches': same_code, 'selected_ids': ids,
                      'indexed_generated_ids': executed_ids,
                      'generated_reports': {identifier: {str(Path(r['result']).resolve()) for r in runs
                          if r.get('role') == 'generated' and r.get('candidate_id') == identifier}
                          for identifier in executed_ids},
                      'runs_index': str(Path(row['runs_index']['path']).resolve()),
                      'complete': row.get('status') == 'completed',
                      'selected_count': len(ids), 'indexed_generated_count': len(executed_ids)}
    return rows, configuration_sha


def summarize(ledger, witnesses, provenance_reviews, campaign_rows, previous=None):
    summaries = []
    provenance = {(r['case'], r['id']): r for r in provenance_reviews}
    preceding = {r['case']: r for r in (previous or {}).get('cases', [])}
    for old in ledger['cases']:
        case = old['case']
        fresh = [r for r in witnesses if r['case'] == case and r['controlled_target_detection']]
        automatic = []
        current = campaign_rows.get(case, {})
        for row in fresh:
            review = provenance.get((case, row['id']), {})
            if (row['origin'] == 'new_search' and current.get('scope_verified')
                and row['id'] in current.get('selected_ids', set())
                and row['id'] in current.get('indexed_generated_ids', set())
                and reviewed(review.get('automatic_provenance', {'verdict': 'unknown'})) is True):
                automatic.append(row['id'])
        inherited = old['inherited_witnesses']
        adjudicated = {row['id'] for row in witnesses if row['case'] == case
                       and (row.get('confirmed_false_alarm') or all(row.get(dimension) is not None for dimension in
                               ('scenario_hit', 'correct_oracle', 'target_failure_match')))}
        false_alarms = {row['id'] for row in witnesses if row['case'] == case and row.get('confirmed_false_alarm')}
        fresh_ids = sorted({r['id'] for r in fresh} | set(preceding.get(case, {}).get('fresh_correct_ids', [])))
        summaries.append({'case': case, 'inherited_ids': [r['id'] for r in inherited],
                          'fresh_correct_ids': fresh_ids,
                          'fixed_configuration_automatic_ids': automatic,
                          'cumulative_correct_witness': bool(inherited or fresh_ids),
                          'fresh_correct_witness': bool(fresh_ids),
                          'fixed_configuration_correct': bool(automatic),
                          'fixed_configuration_warm_replay_correct': bool(automatic) and current.get('oracle_mode') == 'replay',
                          'fixed_configuration_fresh_model_correct': bool(automatic) and current.get('oracle_mode') == 'fresh',
                          'fixed_configuration_no_current_model_correct': bool(automatic) and current.get('oracle_mode') == 'none',
                          'oracle_mode': current.get('oracle_mode', 'not_run'),
                          'campaign_rounds': current.get('rounds', []),
                          'selected_candidates': current.get('selected_count', 0),
                          'indexed_generated_candidates': current.get('indexed_generated_count', 0),
                          'provider_calls': current.get('provider_calls', 0),
                          'semantic_selected_candidates': current.get('semantic_selected_count', 0),
                          'named_outcome_counts': current.get('named_outcome_counts', {}),
                          'unreviewed_failed_candidates': len(current.get('named_failed_ids', set()) - adjudicated),
                          'confirmed_false_alarm_candidates': len(current.get('named_failed_ids', set()) & false_alarms),
                          'campaign_status': 'completed' if current.get('complete') else 'partial' if current else 'not_run',
                          'campaign_source_verified': current.get('scope_verified', False),
                          'historical_axis': old['historical_axis']})
    return summaries


def audit(args):
    ledger = read(args.ledger)
    if [x['case'] for x in ledger['cases']] != CASES or ledger['denominator'] != 17:
        raise ValueError('The denominator and order remain fixed17')
    deliveries = read(args.deliveries)
    for delivery in deliveries:
        if delivery['origin'] == 'baseline_retained':
            raise ValueError('Old witnesses belong to inherited ledger, not fresh deliveries')
        manifest = Path(delivery['execution_manifest']['path']).resolve()
        if not manifest.is_relative_to(OUT.parent):
            raise ValueError('A fresh delivery requires an actual new-round execution manifest')
    fresh = evaluate(SimpleNamespace(ledger=args.ledger, deliveries=args.deliveries, reviews=args.reviews))
    campaign = read(args.campaign) if args.campaign else None
    campaign_rows, configuration = verify_campaign(campaign, ledger, args.campaign)
    # The live coordinator appends cases. Freeze the observed index itself so
    # an incremental checkpoint does not later refer to a changed live file.
    campaign_snapshot = None
    if args.campaign:
        campaign_snapshot = Path(args.output).with_name(Path(args.output).stem + '_campaign_snapshot.json')
        write_new(campaign_snapshot, campaign)
    # Prevent a campaign from borrowing the same candidate ID from a different execution.
    for delivery in deliveries:
        row = campaign_rows.get(delivery['case'])
        if row:
            supplied = read(delivery['runs_json'])
            supplied = supplied['runs'] if isinstance(supplied, dict) else supplied
            observed = {str(Path(r['result']).resolve()) for r in supplied
                        if r.get('role') == 'generated' and r.get('candidate_id') == delivery['id']}
            if not observed or not observed <= row['generated_reports'].get(delivery['id'], set()):
                row['selected_ids'] = row['selected_ids'] - {delivery['id']}
    previous = read(args.previous) if args.previous else None
    if previous:
        if previous['start_utc'] != ledger['start_utc'] or previous['denominator'] != 17:
            raise ValueError('Previous checkpoint must belong to this continuation round')
        for record in previous['inputs'] + previous['fresh_evaluation']['evidence_files'] + previous.get('campaign_evidence_files', []):
            verify_file(record)
    rows = summarize(ledger, fresh['deliveries'], read(args.reviews), campaign_rows, previous)
    counts = {key: sum(bool(r[key]) for r in rows) for key in
              ('cumulative_correct_witness', 'fresh_correct_witness', 'fixed_configuration_correct',
               'fixed_configuration_warm_replay_correct', 'fixed_configuration_fresh_model_correct',
               'fixed_configuration_no_current_model_correct')}
    result = {'denominator': 17, 'start_utc': ledger['start_utc'], 'deadline_utc': ledger['deadline_utc'],
              'counts': counts, 'configuration_sha256': configuration,
              'execution_inventory': {
                  **{status: sum(row['named_outcome_counts'].get(status, 0) for row in rows)
                     for status in ('passed', 'failed', 'not_observed', 'execution_error', 'other')},
                  'confirmed_false_alarm_candidates': sum(row['confirmed_false_alarm_candidates'] for row in rows),
                  'unreviewed_failed_candidates': sum(row['unreviewed_failed_candidates'] for row in rows)},
              'all17_same_campaign_completed': len(campaign_rows) == 17 and all(r['complete'] and r['scope_verified'] for r in campaign_rows.values()),
              'cases': rows, 'fresh_evaluation': fresh,
              'live_campaign_index': str(Path(args.campaign).resolve()) if args.campaign else None,
              'campaign_evidence_files': list({record['path']: record for row in campaign_rows.values()
                                               for record in row.get('evidence_files', [])}.values()),
              'inputs': [freeze_file(args.ledger), freeze_file(args.deliveries), freeze_file(args.reviews)] + ([freeze_file(campaign_snapshot)] if campaign_snapshot else []) + ([freeze_file(args.previous)] if args.previous else []),
              'limits': 'Automation provenance and oracle correctness are separate cited reviews. Manual assertion edits never count as automated. Warm semantic replay reuses historical model judgments and is not a fresh end-to-end model run. No-current-model denotes this campaign, not the entire history of its source tests. N06 remains historical even if regenerated. Counts are development-case results, not population FPR/FNR.'}
    write_new(args.output, result)
    return {'denominator': 17, 'counts': counts, 'all17_same_campaign_completed': result['all17_same_campaign_completed']}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('stage', choices=['init', 'audit'])
    p.add_argument('--ledger', type=Path, default=OUT/'ledger.json')
    p.add_argument('--deliveries', type=Path, default=OUT/'deliveries.json')
    p.add_argument('--reviews', type=Path, default=OUT/'reviews.json')
    p.add_argument('--campaign', type=Path)
    p.add_argument('--previous', type=Path, help='Keep already confirmed witnesses without borrowing their run as this campaign evidence')
    p.add_argument('--output', type=Path, default=OUT/'evaluation.json')
    args=p.parse_args()
    print(json.dumps(initialize(args) if args.stage == 'init' else audit(args)))


if __name__ == '__main__':
    main()
