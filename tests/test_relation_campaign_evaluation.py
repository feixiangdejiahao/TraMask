"""Independent campaign scope checks using coordinator-shaped disk artifacts."""
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
from evaluate_relation_search_continuation import (named_outcomes, summarize, verify_campaign,
                                                 verify_isolated_run, register_execution,
                                                 verify_semantic_frontier)
from evaluate_relational_gap import digest, freeze_file


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True))
    return path


def isolated_go_fixture(tmp_path, status='fail'):
    phase = tmp_path/'executed/group_000/generated'
    view = phase/'isolated/test_hash'
    name = 'TestGC_target'
    raw = phase/'go.runner/test_0000/stdout.txt'
    raw.parent.mkdir(parents=True)
    events = [{'Action': 'run', 'Test': name}, {'Action': 'fail', 'Test': name}]
    raw.write_text(''.join(json.dumps(event)+'\n' for event in events))
    process = {'stdout': str(raw), 'returncode': -9 if status == 'timeout' else 1,
               'timed_out': status == 'timeout', 'command': ['go', 'tool', 'test2json']}
    write(raw.parent/'process.json', process)
    context = write(phase/'context.json', {'source_files': []})
    # A sibling timeout makes the shared phase erroneous. It must not erase
    # the completed target's native terminal event in its independent process.
    summary = write(phase/'go.runner.json', {
        'report': str(phase/'go.jsonl'), 'status': 'error',
        'tests': [{'package': './', 'test': name, 'status': status, 'process': process},
                  {'package': './', 'test': 'TestGC_sibling', 'status': 'timeout'}]})
    write(phase/'result.json', {'error': 'a_sibling_timed_out'})
    write(view/'result.json', {**process, 'isolation_status': status, 'source_context_file': str(context)})
    (view/'stdout.txt').write_bytes(raw.read_bytes())
    (view/'go.jsonl').write_text(json.dumps(events[0])+'\n' if status == 'timeout' else raw.read_text())
    proof = write(view/'provenance.json', {
        'scope': 'one_exact_test_in_one_process', 'package': './', 'test_name': name,
        'source_context_file': str(context), 'source_snapshot': [], 'group_summary': str(summary),
        'status': status, 'raw_evidence': [freeze_file(raw)], 'compiled_binaries': [],
        'derived_report_sha256': digest(view/'go.jsonl')})
    report = write(view/'normalized.json', {
        'status': 'error' if status == 'timeout' else 'fail',
        'tests': [] if status == 'timeout' else [{'id': name, 'status': 'fail'}],
        'isolation': {'status': status, 'provenance': str(proof)}})
    row = {'case': 'N08', 'candidate_id': 'candidate', 'role': 'generated', 'result': str(report),
           'test_ids': [name], 'execution_context': {'context_file': str(context), 'source_snapshot': []}}
    return row, phase, view


def test_isolated_failure_survives_sibling_timeout_but_not_its_own(tmp_path):
    completed, _, _ = isolated_go_fixture(tmp_path/'completed')
    assert verify_isolated_run(completed)
    assert named_outcomes([completed]) == {'candidate': {'failed'}}
    timeout, _, _ = isolated_go_fixture(tmp_path/'timeout', 'timeout')
    assert verify_isolated_run(timeout)
    assert named_outcomes([timeout]) == {'candidate': {'execution_error'}}


def test_isolated_native_output_tampering_is_rejected(tmp_path):
    row, _, view = isolated_go_fixture(tmp_path)
    (view/'stdout.txt').write_text('replaced raw output')
    with pytest.raises(AssertionError, match='Changed raw process output'):
        verify_isolated_run(row)


def test_isolated_normalized_names_may_include_go_package(tmp_path):
    row, _, view = isolated_go_fixture(tmp_path)
    normalized = json.loads((view/'normalized.json').read_text())
    normalized['tests'][0]['id'] = 'example.org/project::TestGC_target'
    write(view/'normalized.json', normalized)
    assert verify_isolated_run(row)


def test_isolated_normalizer_may_retain_only_subtest_leaves(tmp_path):
    row, phase, view = isolated_go_fixture(tmp_path)
    raw = phase/'go.runner/test_0000/stdout.txt'
    raw.write_text(raw.read_text()+json.dumps({'Test': 'TestGC_target/child', 'Action': 'fail'})+'\n')
    (view/'stdout.txt').write_bytes(raw.read_bytes())
    (view/'go.jsonl').write_bytes(raw.read_bytes())
    proof = json.loads((view/'provenance.json').read_text())
    proof.update(raw_evidence=[freeze_file(raw)], derived_report_sha256=digest(view/'go.jsonl'))
    write(view/'provenance.json', proof)
    normalized = json.loads((view/'normalized.json').read_text())
    normalized['tests'][0]['id'] = 'example.org/project::TestGC_target/child'
    write(view/'normalized.json', normalized)
    assert verify_isolated_run(row)


def test_timeout_cannot_be_relabelled_as_completed_test_failure(tmp_path):
    row, phase, view = isolated_go_fixture(tmp_path)
    summary = json.loads((phase/'go.runner.json').read_text())
    summary['tests'][0]['process']['timed_out'] = True
    process = summary['tests'][0]['process']
    write(phase/'go.runner.json', summary)
    write(Path(process['stdout']).parent/'process.json', process)
    result = json.loads((view/'result.json').read_text())
    write(view/'result.json', {**result, 'timed_out': True})
    with pytest.raises(AssertionError, match='Incomplete process'):
        verify_isolated_run(row)


def test_registration_uses_shared_context_for_nested_go_report(tmp_path):
    row, phase, view = isolated_go_fixture(tmp_path)
    source = tmp_path/'generated_test.go'
    source.write_text('package project\n')
    emitted = write(tmp_path/'emitted/manifest.json', {'mounts': [
        {'source': str(source), 'target': '/generated/test.snapshot'}]})
    actual = write(phase.parent/'manifest.json', {'request': {'program': 'candidate'}})
    row.update(manifest=str(emitted), control_ids=[], base_test_id='original')
    runs = write(tmp_path/'runs.json', [row])
    delivery, _ = register_execution('N08', 'candidate', runs, tmp_path/'review/candidate')
    assert delivery['execution_manifest'] == freeze_file(actual)
    assert delivery['test_files'] == [freeze_file(source)]


def campaign_files(tmp_path, mode='replay', round_limit=None, case_budget=None,
                   writer_priority=None, writer_stage_priority=None):
    root, source = tmp_path/'campaign', tmp_path/'source'/'N06'
    corpus = write(source/'corpus.json', {'tests': ['same complete source']})
    code = {}
    for name in ['relation_search/operator.py', 'scripts/execute_relation_search.py']:
        path = root/'algorithm_snapshot'/name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('# frozen algorithm\n')
        code[name] = digest(path)
    configuration = dict(source_root=str(source.parent), cases=['N06'], rounds=2,
                         limit=2, pool=8, strategy='profile', max_edits=4,
                         include_baseline=True, representations_only=False,
                         group_size=2, timeout=20, workers=1,
                         oracle_mode=mode, semantic_budget=1, per_request=1, model_workers=1,
                         oracle_cache_sha256='historical' if mode == 'replay' else None,
                         source_corpus_sha256={'N06': digest(corpus)}, algorithm_sha256=code)
    if writer_priority is not None:
        configuration['writer_priority'] = writer_priority
    global_config = write(root/'configuration.json', configuration)
    local = {**configuration, 'case': 'N06', 'source': str(source)}
    if case_budget is not None:
        local['limit'] = case_budget
    local_config = write(root/'N06/configuration.json', local)
    rounds, previous = [], None
    for index in range(2):
        folder = root/'N06'/f'round_{index:03d}'
        program, semantic, emitted, executed = [folder/name for name in ['prepared', 'semantic', 'emitted', 'executed']]
        candidate = {'id': f'candidate_{index}'}
        stage = dict(stage='prepare', strategy='profile', limit=round_limit or 2, pool=8,
                     max_edits=4, include_baseline=True, representations_only=False,
                     source=str(source), global_configuration_sha256=digest(global_config),
                     previous_sha256=previous, source_sha256={'corpus.json': digest(corpus)},
                     algorithm_sha256=code)
        if writer_priority is not None:
            stage['writer_priority'] = (writer_priority if writer_stage_priority is None
                                        else writer_stage_priority)
        write(program/'stage.json', stage)
        write(program/'candidates.json', {'candidates': [candidate]})
        write(program/'corpus.json', json.loads(corpus.read_text()))
        for relative in code:
            copied = program/'algorithm_snapshot'/relative
            copied.parent.mkdir(parents=True, exist_ok=True)
            copied.write_bytes((root/'algorithm_snapshot'/relative).read_bytes())
        prepared = write(program/'prepare.json', dict(
            source_identity={'corpus.json': digest(corpus)}, algorithm_sha256=code,
            files_sha256={name: digest(program/name) for name in ['stage.json', 'candidates.json', 'corpus.json']}))
        write(semantic/'stage.json', dict(stage='semantic', input=str(program), input_sha256=digest(prepared),
              code_sha256=code, mode=mode, budget=1, per_request=1, model_workers=1,
              cache_sha256=configuration['oracle_cache_sha256']))
        write(semantic/'candidates.json', {'candidates': [candidate]})
        write(semantic/'corpus.json', json.loads(corpus.read_text()))
        write(semantic/'semantic_result.json', dict(provider_calls=1 if mode == 'fresh' else 0,
                                                  selected_ids=['candidate_'+str(index)] if mode == 'fresh' else []))
        if mode == 'fresh':
            write(semantic/'requests/request_000.json', {'offered': {'C0': {'candidate': candidate}}})
            write(semantic/'completions/request_000/manifest.json', {'external_model_calls': 1})
        interpreted = write(semantic/'prepare.json', dict(
            source_prepare=str(prepared), files_sha256={name: digest(semantic/name) for name in
            ['stage.json', 'candidates.json', 'corpus.json', 'semantic_result.json']}))
        write(emitted/'stage.json', dict(stage='emit', input=str(semantic), input_sha256=digest(interpreted),
                                        algorithm_sha256=code, group_size=2, timeout=20))
        artifact = write(emitted/'group_000/manifest.json', dict(original_input=str(semantic)))
        write(executed/'stage.json', dict(stage='run', input=str(emitted), workers=1,
              runner_sha256=code['scripts/execute_relation_search.py'],
              artifacts_sha256={str(artifact.parent): digest(artifact)}))
        report = write(executed/'group_000/generated/normalized.json', {'tests': []})
        runs = write(executed/'runs.json', [{'case': 'N06', 'candidate_id': candidate['id'],
                                          'role': 'generated', 'result': str(report)}])
        write(executed/'checkpoint.json', {'files_sha256': {'runs.json': digest(runs),
              'stage.json': digest(executed/'stage.json'),
              'group_000/generated/normalized.json': digest(report)}, 'result': {'artifacts': 1}})
        previous = digest(write(folder/'feedback.json', {'round': index}))
        rounds.append(dict(round=index, program_prepare_manifest=str(prepared),
                           prepare_manifest=str(interpreted), candidates=str(semantic/'candidates.json'),
                           runs_index=str(runs)))
    document = [dict(case='N06', source_corpus=str(corpus), execution_configuration=str(local_config), rounds=rounds)]
    path = write(root/'campaign.json', document)
    ledger = {'cases': [{'case': 'N06', 'source_corpus': freeze_file(corpus)}]}
    return document, ledger, path


def test_direct_coordinator_two_rounds_are_aggregated(tmp_path):
    document, ledger, path = campaign_files(tmp_path)
    rows, configuration = verify_campaign(document, ledger, path)
    row = rows['N06']
    assert configuration == digest(path.parent/'configuration.json')
    assert row['scope_verified'] and row['complete']
    assert row['selected_ids'] == {'candidate_0', 'candidate_1'}
    assert row['indexed_generated_ids'] == row['selected_ids']
    assert row['oracle_mode'] == 'replay'
    assert row['provider_calls'] == 0
    assert len(row['rounds']) == 2
    assert row['evidence_files']


def test_same_global_sha_cannot_hide_different_case_configuration(tmp_path):
    document, ledger, path = campaign_files(tmp_path, case_budget=1)
    rows, _ = verify_campaign(document, ledger, path)
    assert not rows['N06']['configuration_matches']
    assert not rows['N06']['scope_verified']


def test_actual_prepare_budget_must_match_global_configuration(tmp_path):
    document, ledger, path = campaign_files(tmp_path, round_limit=1)
    rows, _ = verify_campaign(document, ledger, path)
    assert rows['N06']['configuration_matches']
    assert all(not row['configuration_matches'] for row in rows['N06']['rounds'])
    assert not rows['N06']['scope_verified']


@pytest.mark.parametrize('actual_priority', [True, False])
def test_actual_writer_priority_must_match_global_configuration(tmp_path, actual_priority):
    document, ledger, path = campaign_files(
        tmp_path, writer_priority=True, writer_stage_priority=actual_priority)
    rows, _ = verify_campaign(document, ledger, path)
    assert rows['N06']['configuration_matches']
    assert all(row['configuration_matches'] == actual_priority for row in rows['N06']['rounds'])
    assert rows['N06']['scope_verified'] == actual_priority


def test_frozen_reports_cannot_change_after_execution(tmp_path):
    document, ledger, path = campaign_files(tmp_path)
    report = path.parent/'N06/round_001/executed/group_000/generated/normalized.json'
    write(report, {'tests': ['replaced result']})
    with pytest.raises(ValueError, match='Frozen evidence changed'):
        verify_campaign(document, ledger, path)


def test_full_code_snapshot_required_and_tamper_checked(tmp_path):
    document, ledger, path = campaign_files(tmp_path)
    snapshot = path.parent/'algorithm_snapshot/relation_search/operator.py'
    snapshot.unlink()
    rows, _ = verify_campaign(document, ledger, path)
    assert not rows['N06']['scope_verified']
    assert not rows['N06']['algorithm_snapshot_matches']


def test_missing_round_not_completed_without_explicit_exhaustion(tmp_path):
    document, ledger, path = campaign_files(tmp_path)
    document[0]['rounds'].pop()
    rows, _ = verify_campaign(document, ledger, path)
    assert rows['N06']['scope_verified']
    assert not rows['N06']['complete']


def test_fresh_model_accounting_is_separate_from_semantic_replay(tmp_path):
    document, ledger, path = campaign_files(tmp_path, mode='fresh')
    rows, _ = verify_campaign(document, ledger, path)
    row = rows['N06']
    assert row['scope_verified']
    assert row['provider_calls'] == 2
    assert row['semantic_selected_count'] == 2
    assert row['semantic_request_offered_count'] == 2
    assert row['semantic_provider_offered_count'] == 2
    assert row['oracle_mode'] == 'fresh'


def frontier_fixture(tmp_path):
    policy = 'persistent-source-semantic-frontier-v1'
    history = {'old': {'id': 'old', 'edits': ['unchanged old material']},
               'served': {'id': 'served'}, 'new': {'id': 'new'}}
    identity = {'corpus_sha256': 'corpus', 'issue_sha256': 'issue'}
    write(tmp_path/'semantic_frontier.json', {
        'policy': policy, 'source_identity': identity, 'candidates': list(history.values()),
        'selected_ids': ['served', 'old'], 'pending_ids': ['new']})
    write(tmp_path/'semantic_selection.json', {
        'policy': policy, 'budget': 1, 'catalogue_count': 3, 'eligible_count': 2,
        'selected_count': 1, 'pending_count': 1, 'selected': [history['old']],
        'ranking': [{'id': name, 'previously_selected': name == 'served', 'selected': name == 'old'}
                    for name in ['served', 'old', 'new']]})
    return dict(directory=tmp_path,
                stage={'semantic_frontier_policy': policy, 'previous_semantic_sha256': 'previous',
                       'previously_selected': ['served']},
                configuration={'semantic_frontier_policy': policy, 'semantic_budget': 1},
                history=history, served={'served'}, previous_sha256='previous', source_identity=identity,
                model_result={'selected_ids': ['old'], 'previous_selected': ['served', 'old'],
                              'pending_semantic_count': 1, 'semantic_frontier_policy': policy})


def test_pending_old_source_candidate_can_receive_next_oracle_budget(tmp_path):
    args = frontier_fixture(tmp_path)
    valid, evidence, checksum = verify_semantic_frontier(**args)
    assert valid and len(evidence) == 2
    assert checksum == digest(tmp_path/'semantic_frontier.json')


@pytest.mark.parametrize('corruption', ['material', 'source', 'chain', 'repeated', 'foreign', 'ranking'])
def test_persisted_oracle_queue_rejects_unbound_or_repeated_candidates(tmp_path, corruption):
    args = frontier_fixture(tmp_path)
    frontier = json.loads((tmp_path/'semantic_frontier.json').read_text())
    selection = json.loads((tmp_path/'semantic_selection.json').read_text())
    if corruption == 'material':
        frontier['candidates'][0]['edits'] = ['changed oracle input']
    elif corruption == 'source':
        frontier['source_identity']['issue_sha256'] = 'other issue'
    elif corruption == 'chain':
        args['stage']['previous_semantic_sha256'] = 'other previous record'
    elif corruption == 'repeated':
        selection['selected'] = [args['history']['served']]
        args['model_result']['selected_ids'] = ['served']
    elif corruption == 'foreign':
        frontier['candidates'].append({'id': 'never program-selected'})
    else:
        selection['ranking'].reverse()
    write(tmp_path/'semantic_frontier.json', frontier)
    write(tmp_path/'semantic_selection.json', selection)
    assert not verify_semantic_frontier(**args)[0]


def test_named_execution_outcomes_do_not_infer_semantic_correctness(tmp_path):
    clean = write(tmp_path/'normalized.json', {'tests': [
        {'id': 'module::test_pass', 'status': 'pass'},
        {'id': 'module::test_fail', 'status': 'fail'}], 'errors': []})
    broken = write(tmp_path/'broken.json', {'tests': [], 'errors': ['compile_error']})
    runs = [{'candidate_id': key, 'role': 'generated', 'result': str(clean), 'test_ids': [name]}
            for key, name in [('pass', 'test_pass'), ('fail', 'test_fail'), ('missing', 'test_missing')]]
    runs.append({'candidate_id': 'broken', 'role': 'generated', 'result': str(broken), 'test_ids': ['test_missing']})
    outcomes = named_outcomes(runs)
    assert outcomes == {'pass': {'passed'}, 'fail': {'failed'}, 'missing': {'not_observed'}, 'broken': {'execution_error'}}
    ledger = {'cases': [{'case': 'N06', 'inherited_witnesses': [], 'historical_axis': None}]}
    row = summarize(ledger, [], [], {'N06': {'named_failed_ids': {'fail'}}})[0]
    assert row['unreviewed_failed_candidates'] == 1
    assert not row['fixed_configuration_correct']


@pytest.mark.parametrize('mode', ['replay', 'fresh', 'none'])
def test_model_modes_never_merge_their_correct_counts(tmp_path, mode):
    provenance = write(tmp_path/'proof.json', {'source': 'exact program output'})
    ledger = {'cases': [{'case': 'N06', 'inherited_witnesses': [], 'historical_axis': None}]}
    witness = [{'case': 'N06', 'id': 'x', 'origin': 'new_search', 'controlled_target_detection': True}]
    reviews = [{'case': 'N06', 'id': 'x', 'automatic_provenance': {
        'verdict': 'yes', 'reason': 'Program artifact match', 'evidence': [freeze_file(provenance)]}}]
    campaign = {'N06': dict(scope_verified=True, selected_ids={'x'}, indexed_generated_ids={'x'}, oracle_mode=mode)}
    row = summarize(ledger, witness, reviews, campaign)[0]
    assert row['fixed_configuration_correct']
    assert row['fixed_configuration_warm_replay_correct'] == (mode == 'replay')
    assert row['fixed_configuration_fresh_model_correct'] == (mode == 'fresh')
    assert row['fixed_configuration_no_current_model_correct'] == (mode == 'none')


def test_pending_contract_review_does_not_erase_history_or_count_as_reliable():
    ledger = {'cases': [{'case': 'N08', 'inherited_witnesses': [{'id': 'old'}], 'historical_axis': None}]}
    pending = [{'case': 'N08', 'id': 'old', 'status': 'pending_contract_reassessment'}]
    old = summarize(ledger, [], [], {}, reassessments=pending)[0]
    assert old['cumulative_correct_witness']
    assert not old['currently_supported_cumulative_witness']
    new = summarize(ledger, [{'case': 'N08', 'id': 'new', 'origin': 'new_search',
                             'controlled_target_detection': True}], [], {}, reassessments=pending)[0]
    assert new['currently_supported_cumulative_witness']
    assert new['currently_supported_ids'] == ['new']
    assert new['pending_contract_reassessment_ids'] == ['old']
