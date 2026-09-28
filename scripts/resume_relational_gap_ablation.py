"""Resume only frozen emitted tests; second slot waits for another batch to end."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import queue
import subprocess
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[1]


def read(path):
    return json.loads(path.read_text())


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + '\n')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--prefix', type=Path, required=True)
    parser.add_argument('--additional-worker-gate', type=Path, required=True)
    parser.add_argument('--registry', type=Path, default=ROOT/'data/relational_gap_v1/registry.json')
    args = parser.parse_args()
    original = Path(str(args.prefix)+'_pipeline')
    frozen = read(original/'frozen_driver.json')
    ledger = Path(str(args.prefix)+'_resumed_pipeline')
    ledger.mkdir(parents=True, exist_ok=False)
    cases = [row['id'] for row in read(args.registry)]
    emitted = Path(str(args.prefix)+'_emitted')
    output = Path(str(args.prefix)+'_runs')
    if output.exists() and list(output.glob('*/group_*')):
        raise ValueError('This zero-execution resume refuses prior subject groups')
    artifact_hashes = {str((emitted/case/'artifacts.json').resolve()): sha(emitted/case/'artifacts.json') for case in cases}
    protocol = {'prior_freeze': str((original/'frozen_driver.json').resolve()),
                'prior_freeze_sha256': sha(original/'frozen_driver.json'),
                'interruption': read(original/'scheduler_interruption.json'),
                'script_sha256': sha(Path(__file__)), 'provider_calls': 0,
                'registry_order': cases, 'first_worker': 'immediate',
                'second_worker_gate': str(args.additional_worker_gate.resolve()),
                'artifact_lists_sha256': artifact_hashes, 'automatic_retries': 0}
    write(ledger/'resume_protocol.json', protocol)
    (ledger/'scheduler_snapshot.py').write_bytes(Path(__file__).read_bytes())
    pending = queue.Queue()
    for case in cases:
        pending.put(case)
    summaries, lock = [], threading.Lock()

    def verify():
        if sha(Path(__file__)) != protocol['script_sha256']:
            raise RuntimeError('Resume scheduler changed')
        for name, expected in frozen['files_sha256'].items():
            if sha(ROOT/name) != expected:
                raise RuntimeError('Frozen driver changed: '+name)
        for name, expected in {**frozen['dependency_package_inventories_sha256'], **frozen['parent_artifacts_sha256'], **artifact_hashes}.items():
            if sha(Path(name)) != expected:
                raise RuntimeError('Frozen artifact changed: '+name)

    def worker(slot):
        if slot == 2:
            while not args.additional_worker_gate.exists():
                time.sleep(2)
        while True:
            try:
                case = pending.get_nowait()
            except queue.Empty:
                return
            result = {'case': case, 'slot': slot}
            try:
                verify()
                process = subprocess.run([sys.executable, str(ROOT/'scripts/execute_relational_gap_v7.py'), 'run',
                    '--input', str(emitted/case), '--output', str(output/case), '--workers', '1', '--registry', str(args.registry)],
                    cwd=ROOT, capture_output=True, text=True)
                folder = ledger/case
                folder.mkdir(parents=True, exist_ok=True)
                (folder/'run.stdout').write_text(process.stdout)
                (folder/'run.stderr').write_text(process.stderr)
                if process.returncode:
                    raise RuntimeError('run_failed')
                result.update(status='complete', run=json.loads(process.stdout.strip().splitlines()[-1]))
            except Exception as error:
                result.update(status='pipeline_error', error_type=type(error).__name__, error=str(error))
            write(ledger/case/'summary.json', result)
            with lock:
                summaries.append(result)
                write(ledger/'summary.json', summaries)
            print(json.dumps({'case': case, 'slot': slot, 'status': result['status']}), flush=True)
            pending.task_done()

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(worker, slot) for slot in (1, 2)]
        for future in futures:
            future.result()
    runs = []
    for case in cases:
        path = output/case/'runs.json'
        if path.exists():
            runs.extend(read(path))
    write(ledger/'runs.json', runs)
    print(json.dumps({'finished_cases': len(summaries), 'runs': len(runs), 'provider_calls': 0}), flush=True)


if __name__ == '__main__':
    main()
