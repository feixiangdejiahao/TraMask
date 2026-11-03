"""Real commands on synthetic files; replace only the Docker boundary."""
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

from eviweave.artifacts import file_ref, write_json
from eviweave.baseline import run_selected_test
from eviweave import execution
from eviweave.replay.command_guest import execute
from eviweave.replay.state_guest import file_state
from eviweave.test_units import discover


@pytest.fixture
def environment(tmp_path, monkeypatch):
    root = tmp_path / 'repo'
    root.mkdir()
    patch = tmp_path / 'model.patch'
    patch.write_text('')
    output = tmp_path / 'baseline'

    class LocalSession:
        def __init__(self, directory):
            self.output = directory

        def control(self, argv, *, input_bytes):
            request = json.loads(input_bytes)
            data = {p: file_state(root / p.removeprefix('/app/')) for p in request['paths']}
            return SimpleNamespace(stdout=json.dumps(data).encode())

        def run(self, command, label, *, timeout, workdir, env):
            directory = self.output / 'calls' / label
            directory.mkdir(parents=True)
            target = directory / 'output.bin'
            record = execute({'command': command, 'workdir': str(root), 'env': env or {},
                              'timeout': timeout, 'output': str(target)})
            return {**record, 'output': str(target)}

    @contextmanager
    def local_container(image, head, directory):
        yield LocalSession(directory)

    monkeypatch.setattr(execution, 'open_container', local_container)

    def make_manifest(code):
        (root / 'test_x.py').write_text(code)
        unit = discover('/app/test_x.py', code.encode())['units'][0]
        unit['retained_at_submission'] = True
        path = tmp_path / 'manifest.json'
        write_json(path, {'submission_state_validated': True,
                         'checkpoint': {'image_id': 'synthetic', 'head': 'synthetic'},
                         'tests': [unit], 'replay': str(tmp_path)})
        write_json(tmp_path / 'plan.json', {'inputs': {'model.patch': file_ref(patch)}})
        write_json(tmp_path / 'snapshots/submission.json', {'files': [
            {'path': '/app/' + p.name, 'kind': 'file', 'sha256': hashlib.sha256(p.read_bytes()).hexdigest()}
            for p in root.iterdir() if p.is_file()]})
        return path, unit['id']

    return root, output, make_manifest


@pytest.mark.parametrize('body,flags,outcome,reached', [
    ('assert True', '-vv', 'passed', 'named_report_observed'),
    ('assert False', '-vv', 'failed', 'named_report_observed'),
    ('import pytest; pytest.skip("fixture")', '-vv', 'skipped', 'unconfirmed'),
    ('assert True', '-q', 'unconfirmed', 'unconfirmed'),
])
def test_actual_named_results_and_quiet_suite_counts(environment, body, flags, outcome, reached):
    _, output, make_manifest = environment
    path, test_id = make_manifest('def test_x():\n    ' + body + '\n')
    result = run_selected_test(path, test_id, f'{sys.executable} -m pytest test_x.py {flags}', output)
    assert result['test_outcome'] == outcome
    assert result['test_execution'] == reached


def test_build_edit_is_not_a_baseline_of_the_original_test(environment):
    _, output, make_manifest = environment
    path, test_id = make_manifest('def test_x(): assert False\n')
    build = f'''{sys.executable} -c 'from pathlib import Path; Path("test_x.py").write_text("def test_x(): assert True\\n")' '''
    result = run_selected_test(path, test_id, f'{sys.executable} -m pytest test_x.py -vv', output,
                               build_commands=[build])
    assert result['named_reports'][0]['status'] == 'passed'
    assert not result['sources_unchanged'] and result['test_outcome'] == 'unconfirmed'


def test_failed_build_is_recorded_without_running_the_test(environment):
    _, output, make_manifest = environment
    path, test_id = make_manifest('def test_x(): assert True\n')
    result = run_selected_test(path, test_id, f'{sys.executable} -m pytest test_x.py -vv', output,
                               build_commands=['exit 9'])
    assert result['runner_status'] == 'build_failed' and result['test_outcome'] == 'unconfirmed'
    assert json.loads((output / 'result.json').read_bytes())['execution'] is None


def test_build_edit_of_a_support_file_invalidates_the_baseline(environment):
    root, output, make_manifest = environment
    (root / 'conftest.py').write_text('VALUE = 1\n')
    path, test_id = make_manifest('def test_x(): assert True\n')
    build = f'''{sys.executable} -c 'from pathlib import Path; Path("conftest.py").write_text("VALUE = 2\\n")' '''
    result = run_selected_test(path, test_id, f'{sys.executable} -m pytest test_x.py -vv', output,
                               build_commands=[build])
    assert result['named_reports'][0]['status'] == 'passed'
    assert not result['sources_unchanged'] and result['test_outcome'] == 'unconfirmed'


def test_execution_errors_propagate(environment, monkeypatch):
    _, output, make_manifest = environment
    path, test_id = make_manifest('def test_x(): pass\n')
    def broken(*args, **kwargs):
        raise RuntimeError('broken collector')
    monkeypatch.setattr(execution, 'snapshot_paths', broken)
    with pytest.raises(RuntimeError, match='broken collector'):
        run_selected_test(path, test_id, f'{sys.executable} -m pytest test_x.py -vv', output)
    assert not (output / 'baseline.json').exists()
