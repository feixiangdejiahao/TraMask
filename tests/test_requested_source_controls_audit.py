import importlib.util
from pathlib import Path
import sys

SCRIPT_ROOT = Path(__file__).resolve().parents[1] / 'scripts'
sys.path.insert(0, str(SCRIPT_ROOT))
SPEC = importlib.util.spec_from_file_location('requested_control_audit', SCRIPT_ROOT / 'audit_requested_source_controls.py')
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def rows():
    generated = [dict(manifest='A', control_ids=['test_control'])]
    controls = [dict(role='control', manifest='A', test_ids=['test_control'], result='result', base_test_id='source')]
    return generated, controls


def test_every_parameter_instance_must_pass(monkeypatch):
    monkeypatch.setattr(MODULE, 'native', lambda _: ([dict(id='test_control[a]', status='pass'), dict(id='test_control[b]', status='fail')], [], []))
    assert MODULE.inspect_controls(*rows())['status'] == 'source_control_failed_or_errored'


def test_same_name_other_manifest_does_not_count(monkeypatch):
    generated, controls = rows()
    controls[0]['manifest'] = 'B'
    assert MODULE.inspect_controls(generated, controls)['status'] == 'missing_or_unparseable_controls'


def test_skipped_is_not_pass(monkeypatch):
    monkeypatch.setattr(MODULE, 'native', lambda _: ([dict(id='test_control', status='skip')], [], []))
    assert MODULE.inspect_controls(*rows())['status'] == 'source_control_skipped_or_other'


def test_unexecuted_candidate_is_explicit():
    assert MODULE.inspect_controls([], [])['status'] == 'no_matching_emitted_candidate'
