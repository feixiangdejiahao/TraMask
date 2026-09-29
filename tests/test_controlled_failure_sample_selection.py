import importlib.util
from pathlib import Path
import sys

SCRIPT_ROOT = Path(__file__).resolve().parents[1] / 'scripts'
sys.path.insert(0, str(SCRIPT_ROOT))
SPEC = importlib.util.spec_from_file_location('failure_sampler', SCRIPT_ROOT / 'sample_controlled_failures_v3.py')
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_unselected_skips_do_not_hide_named_failure(tmp_path, monkeypatch):
    result = tmp_path / 'result.json'
    result.write_text('{}')
    manifest = tmp_path / 'manifest.json'
    manifest.write_text('{}')
    monkeypatch.setattr(MODULE, 'native', lambda _: ([dict(id=' target', status='fail'), dict(id='other', status='skip')], [], []))
    evidence = MODULE.named_outcomes([dict(result=str(result), manifest=str(manifest), test_ids=['target'])])
    assert [t['id'] for t in evidence[0]['tests']] == [' target']


def test_unobserved_requested_name_is_ineligible(monkeypatch):
    monkeypatch.setattr(MODULE, 'native', lambda _: ([dict(id='other', status='fail')], [], []))
    assert MODULE.named_outcomes([dict(result='unused', test_ids=['target'])]) is None


def test_parser_error_is_not_a_native_failure(monkeypatch):
    monkeypatch.setattr(MODULE, 'native', lambda _: ([dict(id='target', status='fail')], ['run_error'], []))
    assert MODULE.named_outcomes([dict(result='unused', test_ids=['target'])]) is None
