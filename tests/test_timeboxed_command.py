import json
from pathlib import Path
import signal
import subprocess
import sys
import time

import pytest

from scripts.run_timeboxed_command import cleanup_containers, parse_deadline, supervise


def test_expired_deadline_does_not_launch_and_receipt_cannot_be_overwritten(tmp_path):
    receipt = tmp_path/'receipt.json'
    marker = tmp_path/'marker'
    assert supervise([sys.executable, '-c', f'open({str(marker)!r}, "w").close()'],
                     deadline=time.time()-1, receipt=receipt) == 124
    assert not marker.exists()
    assert json.loads(receipt.read_text())['status'] == 'deadline_before_start'
    with pytest.raises(ValueError, match='already exists'):
        supervise([sys.executable, '-c', 'pass'], deadline=time.time()+10, receipt=receipt)


def test_normal_exit_propagates_and_timezone_is_explicit(tmp_path):
    receipt = tmp_path/'receipt.json'
    assert supervise([sys.executable, '-c', 'raise SystemExit(7)'],
                     deadline=time.time()+10, receipt=receipt) == 7
    assert json.loads(receipt.read_text())['status'] == 'command_failed'
    assert parse_deadline('2026-01-01T00:00:00Z') == parse_deadline('2026-01-01T08:00:00+08:00')
    with pytest.raises(ValueError, match='offset'):
        parse_deadline('2026-01-01T00:00:00')


def test_deadline_kills_owned_grandchild_even_when_it_ignores_terminate(tmp_path):
    marker, receipt = tmp_path/'grandchild.pid', tmp_path/'receipt.json'
    grandchild = ('import os, signal, time; '
                  'signal.signal(signal.SIGTERM, signal.SIG_IGN); '
                  f'open({str(marker)!r}, "w").write(str(os.getpid())); time.sleep(60)')
    parent = ('import subprocess, sys, time; '
              f'subprocess.Popen([sys.executable, "-c", {grandchild!r}]); time.sleep(60)')
    start = time.monotonic()
    assert supervise([sys.executable, '-c', parent], deadline=time.time()+1.2,
                     receipt=receipt, grace=.1) == 124
    assert time.monotonic()-start < 5
    pid = int(marker.read_text())
    until = time.monotonic()+2
    while time.monotonic() < until:
        status = Path(f'/proc/{pid}/stat')
        if not status.exists() or status.read_text().split(') ', 1)[1].split()[0] == 'Z':
            break
        time.sleep(.02)
    else:
        pytest.fail('Owned grandchild remains alive after deadline')
    result = json.loads(receipt.read_text())
    assert result['status'] == 'deadline'
    assert result['signals'] == ['SIGTERM', 'SIGKILL']


def test_container_cleanup_requires_mount_inside_own_campaign(tmp_path, monkeypatch):
    output = tmp_path/'campaign'
    calls = []
    containers = [dict(Id='owned', Mounts=[{'Source': str(output/'case/group')}]),
                  dict(Id='other', Mounts=[{'Source': str(tmp_path/'other-campaign')}]),
                  dict(Id='prefix', Mounts=[{'Source': str(tmp_path/'campaign-copy')}])]

    def run(args, **kwargs):
        calls.append(args)
        stdout = 'owned\nother\nprefix\n' if args[1] == 'ps' else json.dumps(containers) if args[1] == 'inspect' else ''
        return subprocess.CompletedProcess(args, 0, stdout, '')

    monkeypatch.setattr(subprocess, 'run', run)
    result = cleanup_containers(output)
    assert result['removed'] == [dict(id='owned', returncode=0)]
    assert [args for args in calls if args[1] == 'rm'] == [['docker', 'rm', '--force', 'owned']]
