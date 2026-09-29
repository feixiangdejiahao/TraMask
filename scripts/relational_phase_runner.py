"""Execute independent source-control and generated-test processes in a container.

The plan contains frozen source snapshots, ordinary commands and time budgets.
No case identifiers, target labels, expected outcomes or model access are used.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n")


def execute_plan(plan, repository=Path('/app'), logs=Path('/replay-logs')):
    repository, logs = Path(repository).resolve(), Path(logs).resolve()
    roles = [phase['role'] for phase in plan['phases']]
    order = {'control': 0, 'source_profile': 1, 'generated': 2}
    if (any(role not in order for role in roles) or len(roles) != len(set(roles))
            or roles != sorted(roles, key=order.__getitem__)):
        raise ValueError('Execution phases must be unique and source-before-generated')
    targets = {item['target'] for phase in plan['phases'] for item in phase['files']}
    originals = {}
    for relative in targets:
        path = (repository / relative).resolve()
        if not path.is_relative_to(repository):
            raise ValueError('Phase target escapes repository')
        originals[relative] = path.read_bytes() if path.exists() else None
    summaries = []
    for phase in plan['phases']:
        role = phase['role']
        if role not in {'control', 'source_profile', 'generated'}:
            raise ValueError('Unsupported execution phase')
        output = logs / role
        output.mkdir(parents=True, exist_ok=False)
        # Restore the same candidate repository's test-file state before each
        # source snapshot; historical files from the previous phase disappear.
        for relative, code in originals.items():
            destination = repository / relative
            if code is None:
                destination.unlink(missing_ok=True)
            else:
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(code)
        for item in phase['files']:
            source = (repository / item['staged']).resolve()
            if not source.is_relative_to(repository):
                raise ValueError('Phase source escapes repository')
            code = source.read_bytes()
            if hashlib.sha256(code).hexdigest() != item['sha256']:
                raise ValueError('Frozen phase source changed')
            destination = repository / item['target']
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(code)
        context = {'role': role, 'source_files': phase['files'],
                   'command': phase['command'], 'timeout': phase['timeout'],
                   'process_isolation': 'separate_process_shared_offline_container',
                   'test_file_restore': 'same_candidate_snapshot_before_each_phase'}
        write(output / 'context.json', context)
        result = {'role': role, 'command': phase['command'], 'timed_out': False}
        started = time.monotonic()
        environment = dict(os.environ, COMBINATION_REPORT_DIR=str(output))
        with (output / 'stdout.txt').open('w') as stdout, (output / 'stderr.txt').open('w') as stderr:
            process = subprocess.Popen(['bash', '-lc', phase['command']], cwd=repository,
                                       env=environment, stdout=stdout, stderr=stderr,
                                       start_new_session=True)
            try:
                result['returncode'] = process.wait(timeout=phase['timeout'])
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
                result.update(returncode=process.returncode, timed_out=True, error='phase_timeout')
        result['elapsed_seconds'] = round(time.monotonic() - started, 3)
        write(output / 'result.json', result)
        summaries.append(result)
    write(logs / 'phases.json', summaries)
    return summaries


if __name__ == '__main__':
    execute_plan(json.loads(Path(sys.argv[1]).read_text()))
