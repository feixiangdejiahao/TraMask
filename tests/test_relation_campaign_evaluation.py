"""Independent campaign scope checks using coordinator-shaped disk artifacts."""
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
from evaluate_relation_search_continuation import named_outcomes, summarize, verify_campaign
from evaluate_relational_gap import digest, freeze_file


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True))
    return path


def campaign_files(tmp_path, mode='replay', round_limit=None, case_budget=None):
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
    assert row['oracle_mode'] == 'fresh'


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
