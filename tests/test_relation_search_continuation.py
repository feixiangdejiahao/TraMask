"""Metric separation: inherited evidence and manual repairs cannot become pipeline wins."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from evaluate_relation_search_continuation import summarize
from evaluate_relational_gap import freeze_file


def ledger(inherited=False):
    return {'cases': [{'case': 'N06', 'inherited_witnesses': [{'id': 'old'}] if inherited else [],
                       'historical_axis': 'previously_executed_relation'}]}


def good(origin='new_search'):
    return {'case': 'N06', 'id': 'new', 'origin': origin, 'controlled_target_detection': True}


def campaign(verified=True):
    return {'N06': {'scope_verified': verified, 'selected_ids': {'new'},
                    'indexed_generated_ids': {'new'}, 'complete': True}}


def review(tmp_path):
    evidence = tmp_path/'provenance.txt'
    evidence.write_text('Frozen program-produced proposal matched the executed source without hand edits.')
    return [{'case': 'N06', 'id': 'new', 'automatic_provenance': {
        'verdict': 'yes', 'reason': 'Independent artifact comparison', 'evidence': [freeze_file(evidence)]}}]


def test_inherited_is_not_fresh_or_fixed_configuration():
    row = summarize(ledger(True), [], [], {})[0]
    assert row['cumulative_correct_witness'] is True
    assert row['fresh_correct_witness'] is False
    assert row['fixed_configuration_correct'] is False
    assert row['campaign_status'] == 'not_run'


def test_manual_repair_is_delivered_but_not_automatic(tmp_path):
    row = summarize(ledger(), [good('manual')], review(tmp_path), campaign())[0]
    assert row['fresh_correct_witness'] is True
    assert row['fixed_configuration_correct'] is False


def test_provenance_unknown_does_not_count_automatic():
    row = summarize(ledger(), [good()], [], campaign())[0]
    assert row['fresh_correct_witness'] is True
    assert row['fixed_configuration_correct'] is False


def test_restricted_corpus_cannot_count_as_full_configuration(tmp_path):
    row = summarize(ledger(), [good()], review(tmp_path), campaign(False))[0]
    assert row['fixed_configuration_correct'] is False


def test_valid_automatic_run_keeps_historical_axis(tmp_path):
    row = summarize(ledger(), [good()], review(tmp_path), campaign())[0]
    assert row['fixed_configuration_correct'] is True
    assert row['historical_axis'] == 'previously_executed_relation'


def test_campaign_checks_prepared_corpus_and_candidate_identity(tmp_path):
    import json
    from evaluate_relation_search_continuation import verify_campaign
    def file(name, value):
        path = tmp_path/name
        path.write_text(json.dumps(value))
        return freeze_file(path)
    config = file('config.json', {'budget': 128})
    code = file('generator.py', 'frozen generator')
    corpus = file('corpus.json', {'tests': ['source']})
    candidates = file('candidates.json', {'candidates': [{'id': 'new'}]})
    runs = file('runs.json', [{'role': 'generated', 'candidate_id': 'new', 'result': str(tmp_path/'result.json')}])
    prepare = file('prepare.json', {'algorithm_sha256': {'generator.py': code['sha256']},
                                  'files_sha256': {'corpus.json': corpus['sha256'], 'candidates.json': candidates['sha256']}})
    campaign_record = {'configuration': config, 'algorithm_files': [{**code, 'algorithm_path': 'generator.py'}],
                      'cases': [{'case': 'N06', 'source_corpus': corpus, 'candidates': candidates,
                                 'prepare_manifest': prepare, 'runs_index': runs,
                                 'configuration_sha256': config['sha256'], 'status': 'completed'}]}
    registered = {'cases': [{'case': 'N06', 'source_corpus': corpus}]}
    rows, _ = verify_campaign(campaign_record, registered)
    assert rows['N06']['scope_verified'] is True
    # A real full-corpus file alongside a prepare manifest for a filtered input
    # must not become a full-corpus result merely by naming the larger file.
    document = json.loads(Path(prepare['path']).read_text())
    document['files_sha256']['corpus.json'] = 'different-filtered-input'
    campaign_record['cases'][0]['prepare_manifest'] = file('filtered-prepare.json', document)
    rows, _ = verify_campaign(campaign_record, registered)
    assert rows['N06']['scope_verified'] is False


def test_previous_witness_survives_without_becoming_current_campaign_hit():
    previous = {'cases': [{'case': 'N06', 'fresh_correct_ids': ['old_focused_execution']}]}
    row = summarize(ledger(), [], [], campaign(), previous)[0]
    assert row['cumulative_correct_witness'] is True
    assert row['fresh_correct_witness'] is True
    assert row['fresh_correct_ids'] == ['old_focused_execution']
    assert row['fixed_configuration_correct'] is False
