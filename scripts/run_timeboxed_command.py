"""Run one owned experiment process group until an absolute UTC deadline."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from relation_search.checkpoint import write


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def parse_deadline(value):
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        raise ValueError('Deadline must include a UTC offset')
    return parsed.timestamp()


def stop_group(process, grace):
    """Only signal the new session created by this supervisor."""
    signals = []
    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(process.pid, sig)
            signals.append(sig.name)
        except ProcessLookupError:
            break
        if sig == signal.SIGTERM:
            # A leader exiting need not mean its grandchildren have stopped.
            # Keep the process handle unreaped until the group is cleaned up.
            time.sleep(grace)
    process.wait()
    return signals


def cleanup_containers(output):
    """Remove only experiment containers mounting this output directory."""
    root = Path(output).resolve()
    removed = []
    try:
        listing = subprocess.run(['docker', 'ps', '-q', '--filter', 'name=relational-gap-'],
                                 capture_output=True, text=True, check=True, timeout=15)
        identifiers = listing.stdout.split()
        if not identifiers:
            return dict(removed=[], status='complete')
        inspected = subprocess.run(['docker', 'inspect', *identifiers], capture_output=True,
                                   text=True, check=True, timeout=15)
        for container in json.loads(inspected.stdout):
            owned = any(mount.get('Source') and Path(mount['Source']).resolve().is_relative_to(root)
                        for mount in container.get('Mounts', []))
            if owned:
                identifier = container['Id']
                stopped = subprocess.run(['docker', 'rm', '--force', identifier],
                                         capture_output=True, text=True, timeout=15)
                removed.append(dict(id=identifier, returncode=stopped.returncode))
        return dict(removed=removed, status='complete' if all(row['returncode'] == 0 for row in removed) else 'error')
    except (OSError, subprocess.SubprocessError, ValueError, KeyError) as error:
        return dict(removed=removed, status='error', error=type(error).__name__)


def supervise(command, *, deadline, receipt, grace=2, docker_root=None):
    if not command or not 0 <= grace <= 30:
        raise ValueError('A command and a grace period in [0, 30] are required')
    receipt = Path(receipt)
    if receipt.exists():
        raise ValueError('Supervisor receipt already exists; inspect the old run first')
    record = dict(command=list(command), deadline_utc=datetime.fromtimestamp(deadline, timezone.utc).isoformat(),
                  started_utc=utc_now(), status='starting', docker_root=str(docker_root) if docker_root else None)
    write(receipt, record)
    remaining = deadline - time.time()
    if remaining <= 0:
        record.update(status='deadline_before_start', finished_utc=utc_now(), returncode=124)
        write(receipt, record)
        return 124
    expires = time.monotonic() + remaining
    process = subprocess.Popen(command, start_new_session=True)
    record.update(status='running', pid=process.pid, process_group=process.pid)
    write(receipt, record)
    requested = []
    previous_handlers = {}

    def interrupted(signum, frame):
        requested.append(signum)

    for sig in (signal.SIGTERM, signal.SIGINT):
        previous_handlers[sig] = signal.signal(sig, interrupted)
    try:
        while True:
            if requested or time.monotonic() >= expires:
                record.update(status='interrupted' if requested else 'deadline', stopping_utc=utc_now())
                write(receipt, record)
                record['signals'] = stop_group(process, grace)
                if docker_root:
                    record['container_cleanup'] = cleanup_containers(docker_root)
                code = 128 + requested[0] if requested else 124
                break
            try:
                code = process.wait(timeout=min(0.5, max(0.001, expires-time.monotonic())))
                record['status'] = 'complete' if code == 0 else 'command_failed'
                break
            except subprocess.TimeoutExpired:
                continue
    finally:
        for sig, handler in previous_handlers.items():
            signal.signal(sig, handler)
    record.update(finished_utc=utc_now(), child_returncode=process.returncode, returncode=code)
    write(receipt, record)
    return code


if __name__ == '__main__':
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('--deadline', type=parse_deadline, required=True)
    parser.add_argument('--receipt', type=Path, required=True)
    parser.add_argument('--grace', type=float, default=2)
    parser.add_argument('--docker-root', type=Path)
    parser.add_argument('command', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ['--'] else args.command
    sys.exit(supervise(command, deadline=args.deadline, receipt=args.receipt,
                       grace=args.grace, docker_root=args.docker_root))
