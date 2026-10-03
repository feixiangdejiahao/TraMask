import json
from pathlib import Path
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from scripts.resume_test_prefix_probe import try_emit, validate_cached
from scripts import resume_test_prefix_probe as probe
from scripts.run_contract_repair_search import frozen, write


def test_explicit_emission_refusal_does_not_request_native_execution(tmp_path):
    artifact = tmp_path / 'emitted/group_000'
    artifact.mkdir(parents=True)
    (artifact / 'emission.json').write_text(json.dumps({
        'unsupported': [{'candidate_id': 'opaque', 'reason': 'overlapping_edits_or_test_name_edit'}]}))
    with patch('scripts.resume_test_prefix_probe.emit', side_effect=AssertionError('must not repeat emission')):
        emitted, refusal = try_emit({}, Path('.'), tmp_path, {'timeout': 180})
    assert emitted is None
    assert refusal['status'] == 'emission_refused'
    assert len(refusal['reports']) == 1


def test_unexplained_emission_failure_remains_fatal(tmp_path):
    artifact = tmp_path / 'emitted/group_000'
    artifact.mkdir(parents=True)
    (artifact / 'emission.json').write_text('{"unsupported": []}')
    with pytest.raises(ValueError, match='without an explicit'):
        try_emit({}, Path('.'), tmp_path, {'timeout': 180})


def test_resume_cannot_reuse_an_outcome_for_changed_program_bytes():
    entry = {'program': {'path': 'test.json', 'sha256': 'new'}, 'rank': 1, 'is_original': False}
    outcome = dict(entry, program={'path': 'test.json', 'sha256': 'old'}, detector_alert=False)
    with pytest.raises(ValueError, match='different frozen program'):
        validate_cached(outcome, entry)


def test_construction_probe_cannot_import_a_detector_alert():
    entry = {'program': {'path': 'test.json', 'sha256': 'same'}, 'rank': 1, 'is_original': False}
    with pytest.raises(ValueError, match='cannot import detector alerts'):
        validate_cached(dict(entry, detector_alert=True), entry)


def test_two_prefix_attempts_keep_immutable_snapshots_and_one_final_result(tmp_path, monkeypatch):
    root = tmp_path / 'run'
    root.mkdir()
    source = tmp_path / 'source'
    source.mkdir()
    write(source / 'corpus.json', {})
    write(tmp_path / 'prior.json', {})
    (tmp_path / 'go.txt').write_text('fixed materializer')
    entries = []
    for rank in (1, 2):
        path = tmp_path / f'program{rank}.json'
        write(path, {'id': f'program{rank}'})
        entries.append({'rank': rank, 'is_original': rank == 2, 'program': frozen(path)})
    p = {'algorithm': {}, 'previous_prepared': frozen(tmp_path / 'prior.json'),
         'go_binding_materializer': frozen(tmp_path / 'go.txt'), 'cached_outcomes': {},
         'deadline_utc': (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
         'timeout': 180, 'max_native_executions': 2, 'items': [
             {'name': 'item', 'case': 'toy', 'parent': 'opaque', 'source': str(source),
              'source_inputs': {'corpus': frozen(source / 'corpus.json')}, 'programs': entries}]}
    write(root / 'prepared.json', p)
    write(root / 'seal.json', frozen(root / 'prepared.json'))
    monkeypatch.setattr(probe, 'try_emit', lambda *args: (tmp_path / 'artifact', None))
    monkeypatch.setattr(probe, 'verify_emission', lambda *args: {'status': 'matched'})
    def execute(candidate, *args):
        return {'controlled_failure': candidate['id'] == 'program2',
                'controls': {'status': 'all_source_controls_passed'}}
    monkeypatch.setattr(probe, 'execute', execute)
    summary = probe.run(SimpleNamespace(input=root))
    assert summary['native_executions'] == 2
    result = json.loads((root / 'cases/item/result.json').read_text())
    assert len(result['attempts']) == 2 and result['first_failure']['rank'] == 2
    assert len(list((root / 'cases/item').glob('result_at_rank_*.json'))) == 2
