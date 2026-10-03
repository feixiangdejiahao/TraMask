import json
from pathlib import Path
from unittest.mock import patch

import pytest

from scripts.resume_test_prefix_probe import try_emit, validate_cached


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
