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


def verify_isolated_run(row):
    """Bind a per-test Go view to its own process, without sibling errors."""
    report = Path(row['result'])
    normalized = read(report)
    isolation = normalized.get('isolation')
    if not isolation or 'provenance' not in isolation:
        return []
    proof_path = Path(isolation['provenance'])
    proof, result = read(proof_path), read(report.parent/'result.json')
    evidence = [freeze_file(p) for p in (report, proof_path, report.parent/'result.json')]
    for record in proof.get('raw_evidence', []) + proof.get('compiled_binaries', []):
        verify_file(record)
        evidence.append(record)
    phase = Path(row['execution_context']['context_file']).resolve().parent
    context = read(phase/'context.json')
    assert _path(proof['source_context_file']) == _path(phase/'context.json'), 'Wrong isolated source context'
    assert _path(result['source_context_file']) == _path(phase/'context.json'), 'Wrong process source context'
    assert proof['source_snapshot'] == context['source_files'] == row['execution_context']['source_snapshot'], 'Wrong isolated source snapshot'
    summary_path = Path(proof['group_summary'])
    assert summary_path.resolve().parent == phase, 'Wrong isolated group summary'
    summary = read(summary_path)
    matches = [item for item in summary.get('tests', []) if
               item['package'] == proof['package'] and item['test'] == proof['test_name']]
    selected = matches[0] if len(matches) == 1 else None
    status = selected['status'] if selected else 'missing_isolated_execution'
    assert status == proof['status'] == isolation['status'] == result['isolation_status'], 'Inconsistent isolated status'
    assert row.get('test_ids') == [proof['test_name']], 'Isolated process must bind one exact declared test'
    assert proof['scope'] == 'one_exact_test_in_one_process'
    assert digest(report.parent/'go.jsonl') == proof['derived_report_sha256'], 'Changed isolated report'
    evidence.extend(freeze_file(p) for p in (summary_path, phase/'context.json', report.parent/'go.jsonl'))
    process = (selected or {}).get('process', {})
    assert all(result.get(key) == value for key, value in process.items()), 'Process result differs from sidecar'
    if process.get('stdout'):
        relative = Path(process['stdout']).relative_to(Path(summary['report']).parent)
        raw_path = (phase/relative).resolve()
        assert raw_path.is_relative_to(phase), 'Raw report escapes phase'
        assert read(raw_path.parent/'process.json') == process, 'Unbound isolated process'
        assert raw_path.read_bytes() == (report.parent/'stdout.txt').read_bytes(), 'Changed raw process output'
        if status in {'pass', 'fail', 'skip'}:
            assert not process.get('timed_out') and not process.get('error'), 'Incomplete process cannot be a test outcome'
            assert raw_path.read_bytes() == (report.parent/'go.jsonl').read_bytes(), 'Completed report must be exact raw stdout'
            events = [json.loads(line) for line in raw_path.read_text().splitlines()]
            terminal = [event['Action'] for event in events if event.get('Test') == proof['test_name']
                        and event.get('Action') in {'pass', 'fail', 'skip'}]
            assert terminal and terminal[-1] == status, 'No matching native terminal event'
        evidence.extend(freeze_file(p) for p in (raw_path, raw_path.parent/'process.json', report.parent/'stdout.txt'))
    tests, errors, _ = runtime_tests(report)
    if status not in {'pass', 'fail', 'skip'}:
        assert errors or normalized.get('errors'), 'Incomplete isolated test must remain an execution error'
    else:
        native = {event['Test']: event['Action'] for event in events
                  if event.get('Test') and event.get('Action') in {'pass', 'fail', 'skip'}}
        actual = [test for test in tests if matches_runtime(test['id'], proof['test_name'])]
        # The frozen normalizer retains leaves when a Go test has subtests.
        assert actual and all(native.get(test['id'].rsplit('::', 1)[-1]) == test['status']
                              for test in actual), 'Normalized outcome differs from native test'
        if status == 'fail' and not any(test['status'] == 'fail' for test in actual):
            assert errors or normalized.get('errors'), 'A dropped parent failure must not become a pass'
    return evidence


def register_execution(case, candidate_id, runs_json, output, origin='new_search'):
    """Register an exact execution, including Go views nested under a phase."""
    rows = read(runs_json)
    matches = [row for row in rows if row['case'] == case and row.get('candidate_id') == candidate_id
               and row['role'] == 'generated']
    if len(matches) != 1:
        raise ValueError('One exact generated execution must be selected')
    generated = matches[0]
    selected = [row for row in rows if row['case'] == case and
                (row.get('candidate_id') == candidate_id or
                 (row['role'] == 'control' and row.get('manifest') == generated.get('manifest')
                  and set(row['test_ids']) & set(generated['control_ids'])))]
    for row in selected:
        verify_isolated_run(row)
    manifest = read(generated['manifest'])
    files = [freeze_file(Path(mount['source'])) for mount in manifest['mounts']
             if '/generated/' in mount['target'] and mount['target'].endswith('.snapshot')]
    if not files:
        raise ValueError('Phase manifest has no generated source snapshot')
    context = generated.get('execution_context', {}).get('context_file')
    actual = Path(context).parent.parent/'manifest.json' if context else Path(generated['result']).parent.parent/'manifest.json'
    if read(actual).get('request', {}).get('program') != 'candidate':
        raise ValueError('Registration requires actual candidate Docker manifest')
    index = output.with_name(output.name + '_runtime_index.json')
    write_new(index, selected)
    delivery = dict(case=case, id=candidate_id, origin=origin, execution_scope='full_repository',
                    test_files=files, source_validation=[generated['base_test_id']], runs_json=str(index.resolve()),
                    execution_manifest=freeze_file(actual))
    write_new(output.with_name(output.name + '_deliveries.json'), [delivery])
    return delivery, selected


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


def verify_semantic_frontier(directory, stage, configuration, history, served,
                             previous_sha256, source_identity, model_result):
    """Validate a persisted queue against source material seen in prior rounds.

    This checks receipts and queue transitions without importing the selector.
    A valid queue is not evidence that its ranking finds a correct oracle.
    """
    frontier_record = freeze_file(directory/'semantic_frontier.json')
    selection_record = freeze_file(directory/'semantic_selection.json')
    frontier, selection = read(frontier_record['path']), read(selection_record['path'])
    catalogue = frontier.get('candidates', [])
    catalogue_ids = [row['id'] for row in catalogue]
    ranking = selection.get('ranking', [])
    ranking_ids = [row['id'] for row in ranking]
    chosen = selection.get('selected', [])
    chosen_ids = [row['id'] for row in chosen]
    pending = [identifier for identifier in ranking_ids if identifier not in served]
    budget = configuration['semantic_budget']
    policy = configuration.get('semantic_frontier_policy')
    checks = (
        policy == 'persistent-source-semantic-frontier-v1',
        stage.get('semantic_frontier_policy') == policy,
        stage.get('previous_semantic_sha256') == previous_sha256,
        set(stage.get('previously_selected', [])) == served,
        frontier.get('policy') == selection.get('policy') == policy,
        frontier.get('source_identity') == source_identity,
        len(catalogue_ids) == len(set(catalogue_ids)) == len(history),
        {row['id']: row for row in catalogue} == history,
        len(ranking_ids) == len(set(ranking_ids)) == len(history),
        set(ranking_ids) == set(history),
        all(row.get('previously_selected') == (row['id'] in served) for row in ranking),
        chosen_ids == pending[:budget] == model_result.get('selected_ids', []),
        all(row == history.get(row['id']) for row in chosen),
        all(row.get('selected') == (row['id'] in chosen_ids) for row in ranking),
        set(frontier.get('selected_ids', [])) == served | set(chosen_ids),
        frontier.get('pending_ids') == pending[budget:],
        selection.get('budget') == budget,
        selection.get('catalogue_count') == len(history),
        selection.get('eligible_count') == len(pending),
        selection.get('selected_count') == len(chosen),
        selection.get('pending_count') == model_result.get('pending_semantic_count') == len(pending[budget:]),
        model_result.get('semantic_frontier_policy') == policy,
        set(model_result.get('previous_selected', [])) == served | set(chosen_ids),
    )
    return all(checks), [frontier_record, selection_record], frontier_record['sha256']


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
        previous_feedback, previous_semantic = None, None
        semantic_history, semantic_served = {}, set()
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
                               and semantic_stage.get('batch_recovery') == configuration.get('batch_recovery')
                               and semantic_stage.get('semantic_frontier_policy') == configuration.get('semantic_frontier_policy')
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
            for candidate in program_candidates:
                if candidate['id'] in semantic_history and semantic_history[candidate['id']] != candidate:
                    raise ValueError('Historical program candidate material changed')
                semantic_history[candidate['id']] = candidate
            runs = read(runs_record['path'])
            runs = runs['runs'] if isinstance(runs, dict) else runs
            for run in runs:
                evidence.extend(verify_isolated_run(run))
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
            replay = read(semantic_dir/'semantic_replay.json') if (semantic_dir/'semantic_replay.json').exists() else {}
            request_offered, provider_offered, actual_calls = set(), set(), 0
            request_material_ok = True
            request_paths = sorted((semantic_dir/'requests').glob('request_*.json'))
            for request_path in request_paths:
                evidence.append(freeze_file(request_path))
                offered_rows = [row['candidate'] for row in read(request_path).get('offered', {}).values()]
                offered = {row['id'] for row in offered_rows}
                request_material_ok = request_material_ok and all(
                    row == semantic_history.get(row['id']) for row in offered_rows)
                request_offered |= offered
                completion = semantic_dir/'completions'/request_path.stem
                provider_manifest = completion/'manifest.json'
                if provider_manifest.exists():
                    evidence.extend(freeze_file(path) for path in sorted(completion.rglob('*')) if path.is_file())
                    calls = read(provider_manifest).get('external_model_calls', 0)
                    actual_calls += calls
                    if calls:
                        provider_offered |= offered
            if configuration.get('oracle_mode') == 'fresh':
                selected_for_model = set(model_result.get('selected_ids', []))
                eligible_ids = {row['id'] for row in program_candidates}
                frontier_ok = True
                if configuration.get('semantic_frontier_policy'):
                    frontier_ok, frontier_evidence, previous_semantic = verify_semantic_frontier(
                        semantic_dir, semantic_stage, configuration, semantic_history, semantic_served,
                        previous_semantic, {'corpus_sha256': digest(program_dir/'corpus.json'),
                                            'issue_sha256': digest(program_dir/'issue.md')}, model_result)
                    evidence.extend(frontier_evidence)
                    eligible_ids = set(semantic_history)
                round_config_ok = (round_config_ok and len(selected_for_model) <= configuration['semantic_budget']
                                   and selected_for_model <= eligible_ids and frontier_ok and request_material_ok
                                   and request_offered <= selected_for_model
                                   and actual_calls == model_result.get('provider_calls', 0))
                semantic_served |= selected_for_model
            rounds.append({'round': index, 'scope_verified': all((round_config_ok, round_code_ok, round_source_ok, chain_ok, candidates_ok, execution_ok)),
                           'configuration_matches': round_config_ok, 'algorithm_snapshot_matches': round_code_ok,
                           'source_corpus_matches': round_source_ok, 'artifact_chain_matches': chain_ok,
                           'selected_candidates_match': candidates_ok, 'execution_index_matches': execution_ok,
                           'selected_count': len(ids), 'indexed_generated_count': len(run_ids),
                           'provider_calls': model_result.get('provider_calls', 0),
                           'semantic_selected_count': len(model_result.get('selected_ids', [])),
                           'semantic_request_count': len(request_paths),
                           'semantic_request_offered_count': len(request_offered),
                           'semantic_provider_offered_count': len(provider_offered),
                           'cache_consulted_count': replay.get('counts', {}).get('originals', 0),
                           'cache_hit_parent_count': len({row['parent'] for row in replay.get('records', [])}),
                           'cache_revision_count': replay.get('counts', {}).get('replayed', 0)})
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
                      **{key: sum(row[key] for row in rounds) for key in
                         ('cache_consulted_count', 'cache_hit_parent_count', 'cache_revision_count',
                          'semantic_request_count', 'semantic_request_offered_count', 'semantic_provider_offered_count')},
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


def summarize(ledger, witnesses, provenance_reviews, campaign_rows, previous=None, reassessments=()):
    summaries = []
    provenance = {(r['case'], r['id']): r for r in provenance_reviews}
    preceding = {r['case']: r for r in (previous or {}).get('cases', [])}
    pending = {(row['case'], row['id']) for row in reassessments
               if row['status'] == 'pending_contract_reassessment'}
    for old in ledger['cases']:
        case = old['case']
        fresh = [r for r in witnesses if r['case'] == case and r['controlled_target_detection']
                 and (case, r['id']) not in pending]
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
        historical_ids = {r['id'] for r in inherited} | set(fresh_ids)
        reliable_ids = sorted(identifier for identifier in historical_ids if (case, identifier) not in pending)
        summaries.append({'case': case, 'inherited_ids': [r['id'] for r in inherited],
                          'fresh_correct_ids': fresh_ids,
                          'fixed_configuration_automatic_ids': automatic,
                          'cumulative_correct_witness': bool(inherited or fresh_ids),
                          'currently_supported_cumulative_witness': bool(reliable_ids),
                          'currently_supported_ids': reliable_ids,
                          'pending_contract_reassessment_ids': sorted(identifier for identifier in historical_ids
                                                                     if (case, identifier) in pending),
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
                          **{key: current.get(key, 0) for key in
                             ('cache_consulted_count', 'cache_hit_parent_count', 'cache_revision_count',
                              'semantic_request_count', 'semantic_request_offered_count', 'semantic_provider_offered_count')},
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
    isolated_evidence = []
    for delivery in deliveries:
        if delivery['origin'] == 'baseline_retained':
            raise ValueError('Old witnesses belong to inherited ledger, not fresh deliveries')
        manifest = Path(delivery['execution_manifest']['path']).resolve()
        if not manifest.is_relative_to(OUT.parent):
            raise ValueError('A fresh delivery requires an actual new-round execution manifest')
        for row in read(delivery['runs_json']):
            isolated_evidence.extend(verify_isolated_run(row))
    fresh = evaluate(SimpleNamespace(ledger=args.ledger, deliveries=args.deliveries, reviews=args.reviews))
    fresh['evidence_files'] = list({record['path']: record for record in
                                  fresh['evidence_files'] + isolated_evidence}.values())
    reassessment_path = OUT/'semantic_reassessments_v1.json'
    reassessments = read(reassessment_path) if reassessment_path.exists() else []
    pending = {(row['case'], row['id']) for row in reassessments
               if row['status'] == 'pending_contract_reassessment'}
    for reassessment in reassessments:
        for record in reassessment['evidence']:
            verify_file(record)
    for row in fresh['deliveries']:
        if (row['case'], row['id']) in pending:
            row.update(correct_oracle=None, correct_test_delivered=False,
                       controlled_target_detection=False, unknown_failure=row['named_test_failure'],
                       semantic_reassessment='pending_contract_reassessment')
    for case_row in fresh['cases']:
        selected = [row for row in fresh['deliveries'] if row['case'] == case_row['case']]
        case_row.update(correct_test_delivered=any(row['correct_test_delivered'] for row in selected),
                        controlled_target_detection=any(row['controlled_target_detection'] for row in selected),
                        new_search_detection=any(row['controlled_target_detection'] and row['origin'] == 'new_search'
                                                 for row in selected),
                        baseline_retained=any(row['correct_test_delivered'] and row['origin'] == 'baseline_retained'
                                              for row in selected))
    fresh['counts'] = {name: sum(row[name] for row in fresh['cases']) for name in fresh['counts']}
    fresh['all_17_correct_tests_delivered'] = all(row['controlled_target_detection'] for row in fresh['cases'])
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
    rows = summarize(ledger, fresh['deliveries'], read(args.reviews), campaign_rows, previous, reassessments)
    schedule = OUT.parent/'resource_schedule_v2.json'
    schedule_record = freeze_file(schedule) if schedule.exists() else None
    counts = {key: sum(bool(r[key]) for r in rows) for key in
              ('cumulative_correct_witness', 'currently_supported_cumulative_witness', 'fresh_correct_witness', 'fixed_configuration_correct',
               'fixed_configuration_warm_replay_correct', 'fixed_configuration_fresh_model_correct',
               'fixed_configuration_no_current_model_correct')}
    result = {'denominator': 17, 'start_utc': ledger['start_utc'], 'deadline_utc': ledger['deadline_utc'],
              'counts': counts, 'configuration_sha256': configuration,
              'semantic_reassessments': reassessments,
              'execution_inventory': {
                  **{status: sum(row['named_outcome_counts'].get(status, 0) for row in rows)
                     for status in ('passed', 'failed', 'not_observed', 'execution_error', 'other')},
                  'confirmed_false_alarm_candidates': sum(row['confirmed_false_alarm_candidates'] for row in rows),
                  'unreviewed_failed_candidates': sum(row['unreviewed_failed_candidates'] for row in rows)},
              'semantic_inventory': {key: sum(row[key] for row in rows) for key in
                                     ('provider_calls', 'semantic_selected_candidates', 'cache_consulted_count',
                                      'cache_hit_parent_count', 'cache_revision_count', 'semantic_request_count',
                                      'semantic_request_offered_count', 'semantic_provider_offered_count')},
              'all17_same_campaign_completed': len(campaign_rows) == 17 and all(r['complete'] and r['scope_verified'] for r in campaign_rows.values()),
              'cases': rows, 'fresh_evaluation': fresh,
              'live_campaign_index': str(Path(args.campaign).resolve()) if args.campaign else None,
              'resource_schedule': schedule_record,
              'campaign_evidence_files': list({record['path']: record for row in campaign_rows.values()
                                               for record in row.get('evidence_files', [])}.values()),
              'inputs': [freeze_file(args.ledger), freeze_file(args.deliveries), freeze_file(args.reviews)] + ([freeze_file(campaign_snapshot)] if campaign_snapshot else []) + ([freeze_file(args.previous)] if args.previous else []) + ([schedule_record] if schedule_record else []) + ([freeze_file(reassessment_path)] if reassessments else []),
              'limits': 'Automation provenance and oracle correctness are separate cited reviews. Manual assertion edits never count as automated. Warm semantic replay reuses historical model judgments and consults all program-selected candidates; fresh model requests apply a separate bounded semantic selection first. These modes do not differ only in provider stability. No-current-model denotes this campaign, not the entire history of its source tests. N06 remains historical even if regenerated. Counts are development-case results, not population FPR/FNR. Concurrent campaigns share host resources; elapsed wall time is budget accounting, not an isolated fair speed comparison.'}
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
