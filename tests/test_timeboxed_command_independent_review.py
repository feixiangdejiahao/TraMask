"""Independent ownership checks for experiment deadline cleanup."""
import json
import os
import signal
import subprocess
import sys
import time

from scripts.run_timeboxed_command import cleanup_containers, supervise


def test_deadline_does_not_signal_unrelated_process_session(tmp_path):
    foreign = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'],
                               start_new_session=True)
    try:
        result = supervise([sys.executable, '-c', 'import time; time.sleep(60)'],
                           deadline=time.time() + .3,
                           receipt=tmp_path/'receipt.json', grace=.01)
        assert result == 124
        assert foreign.poll() is None
        receipt = json.loads((tmp_path/'receipt.json').read_text())
        assert receipt['process_group'] != foreign.pid
    finally:
        if foreign.poll() is None:
            os.killpg(foreign.pid, signal.SIGKILL)
        foreign.wait()


def test_container_cleanup_resolves_paths_and_preserves_other_campaigns(tmp_path, monkeypatch):
    root = tmp_path/'this-campaign'
    root.mkdir()
    other = tmp_path/'other-campaign'
    other.mkdir()
    (root/'external').symlink_to(other, target_is_directory=True)
    calls = []
    containers = [
        dict(Id='owned', Mounts=[{'Source': str(root/'N01'/'manifest.json')}]),
        dict(Id='external', Mounts=[{'Source': str(root/'external'/'manifest.json')}]),
        dict(Id='prefix', Mounts=[{'Source': str(tmp_path/'this-campaign-other'/'manifest.json')}]),
    ]

    def run(args, **kwargs):
        calls.append(args)
        output = 'owned external prefix' if args[1] == 'ps' else json.dumps(containers) if args[1] == 'inspect' else ''
        return subprocess.CompletedProcess(args, 0, output, '')

    monkeypatch.setattr(subprocess, 'run', run)
    result = cleanup_containers(root)
    assert result['removed'] == [dict(id='owned', returncode=0)]
    assert [args for args in calls if args[1] == 'rm'] == [['docker', 'rm', '--force', 'owned']]


def test_failed_owned_container_removal_is_not_reported_complete(tmp_path, monkeypatch):
    root = tmp_path/'campaign'

    def run(args, **kwargs):
        if args[1] == 'ps':
            return subprocess.CompletedProcess(args, 0, 'owned', '')
        if args[1] == 'inspect':
            return subprocess.CompletedProcess(args, 0, json.dumps([
                dict(Id='owned', Mounts=[{'Source': str(root/'N01'/'manifest.json')}])]), '')
        return subprocess.CompletedProcess(args, 1, '', 'removal failed')

    monkeypatch.setattr(subprocess, 'run', run)
    result = cleanup_containers(root)
    assert result['removed'] == [dict(id='owned', returncode=1)]
    assert result['status'] != 'complete'
