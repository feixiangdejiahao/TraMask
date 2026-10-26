import json
from pathlib import Path

import pytest

from scripts import run_automatic_augmentation_goal_diagnostics as diagnostic


def make_protocol(tmp_path, monkeypatch):
    payload_path = tmp_path / 'automatic_payload.json'
    payload = {'evidence_catalog': [{'evidence_id': 'E001', 'kind': 'public_issue'}],
               'original_test': 'unchanged test', 'trajectory_evidence': ['original step']}
    diagnostic.base.write(payload_path, payload)
    seed = {'seed_alias': 'S001', 'evidence_id': 'E002', 'base_test_id': 'a.py:10:test_a'}
    record = {'cases': [{'case': 'N01', 'source': 'original', 'repository': 'repo', 'inputs': {},
                        'batches': [{'batch_id': 'B01', 'candidates': [seed],
                                     'history_payload': diagnostic.base.receipt(payload_path)}]}]}
    diagnostic.base.write(tmp_path / 'prepared.json', record)
    goal = {key: 'source-supported text' for key in diagnostic.GOAL_FIELDS}
    goal['missing_evidence'] = []
    manual = tmp_path / 'manual.json'
    diagnostic.base.write(manual, {'goals': [{'case': 'N01', 'base_test_id': seed['base_test_id'],
                                             'goal': goal, 'additional_original_source': ['not injected'],
                                             'old_failure': 'must not enter'}]})
    monkeypatch.setattr(diagnostic, 'FILES', [manual])
    monkeypatch.setattr(diagnostic.main, 'load_protocol', lambda root: record)
    return payload_path, payload, manual


def test_diagnostic_keeps_payload_and_only_injects_reviewed_goal(tmp_path, monkeypatch):
    payload_path, payload, manual = make_protocol(tmp_path, monkeypatch)
    record = diagnostic.prepare(tmp_path, ['N01'])
    row = record['rows'][0]
    assert diagnostic.base.read(payload_path) == payload
    assert row['goal']['seed_alias'] == 'S001'
    assert row['goal']['evidence_ids'] == ['E001', 'E002']
    assert 'must not enter' not in json.dumps(record)
    assert 'not injected' not in json.dumps(record)
    assert record['main_method'] is False
    assert diagnostic.prepare(tmp_path, ['N01']) == record
    with pytest.raises(ValueError, match='diagnostic_selection_changed'):
        diagnostic.prepare(tmp_path, ['N01', 'P7'])
    manual.write_text('{}')
    with pytest.raises(ValueError):
        diagnostic.prepare(tmp_path, ['N01'])


def test_unknown_target_is_not_silently_dropped(tmp_path, monkeypatch):
    make_protocol(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match='unknown_diagnostic_case'):
        diagnostic.prepare(tmp_path, ['P7'])
