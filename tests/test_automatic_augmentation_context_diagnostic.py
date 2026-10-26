import pytest
from scripts import run_automatic_augmentation_context_diagnostic as diagnostic


def test_context_completion_keeps_original_bytes_and_excludes_human_labels(tmp_path):
    path = tmp_path / 'api.ts'
    path.write_text('first\nsecond\n')
    span = dict(path='api.ts', start_line=2, end_line=2, text='second\n',
                source_file=diagnostic.base.receipt(path), goal='secret label')
    payload = {'original_test': 'fixed', 'trajectory_evidence': ['fixed step']}
    completed = diagnostic.complete_context(payload, [span])
    assert completed.pop('supplemental_original_source') == [dict(
        evidence_id='D0001', kind='original_repository_source', path='api.ts',
        start_line=2, end_line=2, text='second\n')]
    assert completed == payload
    span['text'] = 'wrong\n'
    with pytest.raises(ValueError, match='manual_original_source_span_mismatch'):
        diagnostic.complete_context(payload, [span])
