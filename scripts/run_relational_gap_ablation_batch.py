"""Uniform no-model whole-source-observation ablation, two Docker slots."""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
from pathlib import Path
import subprocess
import sys
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
    parser.add_argument('--source-batch-root', type=Path, required=True)
    parser.add_argument('--source-emitted-root', type=Path, required=True)
    parser.add_argument('--source-freeze', type=Path, required=True)
    parser.add_argument('--prefix', type=Path, required=True)
    parser.add_argument('--execution-gate', type=Path)
    parser.add_argument('--registry', type=Path, default=ROOT/'data/relational_gap_v1/registry.json')
    parser.add_argument('--dependency-packages-root', type=Path, default=ROOT/'data/relational_gap_v1_dependency_packages')
    args = parser.parse_args()
    ledger = Path(str(args.prefix) + '_pipeline')
    ledger.mkdir(parents=True, exist_ok=False)
    previous = read(args.source_freeze)
    hashes = dict(previous['files_sha256'])
    for name, expected in hashes.items():
        if sha(ROOT/name) != expected:
            raise ValueError('Previously frozen dependency changed: ' + name)
    for name in ['relational_gap/oracle_retention_ablation.py', 'scripts/prepare_relational_gap_ablation.py',
                 'scripts/execute_relational_gap_v7.py', 'scripts/run_relational_gap_ablation_batch.py']:
        hashes[name] = sha(ROOT/name)
    package_hashes = previous['dependency_package_inventories_sha256']
    cases = [row['id'] for row in read(args.registry)]
    source_hashes = {}
    for case in cases:
        for path in [args.source_batch_root/case/'prepare.json', args.source_emitted_root/case/'accepted.json']:
            source_hashes[str(path.resolve())] = sha(path)
    write(ledger/'frozen_driver.json', {'files_sha256': hashes,
        'dependency_package_inventories_sha256': package_hashes, 'parent_artifacts_sha256': source_hashes,
        'provider_calls': 0, 'docker_concurrency': 2, 'preparation_concurrency': 4, 'automatic_retries': 0,
        'execution_gate': str(args.execution_gate) if args.execution_gate else None,
        'per_case_budget': 128, 'selection': 'all_successfully_restored_offered_source_q'})
    for name in hashes:
        destination = ledger/'driver_snapshot'/name
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes((ROOT/name).read_bytes())

    def stage(case, name, script, command):
        for relative, expected in hashes.items():
            if sha(ROOT/relative) != expected:
                raise RuntimeError('Frozen driver changed: ' + relative)
        for path, expected in {**package_hashes, **source_hashes}.items():
            if sha(Path(path)) != expected:
                raise RuntimeError('Frozen source artifact changed: ' + path)
        process = subprocess.run([sys.executable, str(ROOT/script), *command], cwd=ROOT, capture_output=True, text=True)
        directory = ledger/case
        directory.mkdir(parents=True, exist_ok=True)
        (directory/(name+'.stdout')).write_text(process.stdout)
        (directory/(name+'.stderr')).write_text(process.stderr)
        if process.returncode:
            raise RuntimeError('stage_failed:' + name)
        summary = json.loads(process.stdout.strip().splitlines()[-1])
        print(json.dumps({'case': case, 'stage': name, 'summary': summary}), flush=True)
        return summary

    def prepare_worker(case):
        prepared = args.prefix/case
        emitted = Path(str(args.prefix)+'_emitted')/case
        executed = Path(str(args.prefix)+'_runs')/case
        result = {'case': case, 'stages': {}}
        try:
            result['stages']['prepare'] = stage(case, 'prepare', 'scripts/prepare_relational_gap_ablation.py',
                ['--source', str(args.source_batch_root/case), '--emitted', str(args.source_emitted_root/case), '--output', str(prepared)])
            result['stages']['emit'] = stage(case, 'emit', 'scripts/execute_relational_gap_v7.py',
                ['emit', '--input', str(prepared), '--output', str(emitted), '--dependency-packages-root', str(args.dependency_packages_root)])
            result.update(status='ready_for_execution', emitted=str(emitted), executed=str(executed))
        except Exception as error:
            result.update(status='pipeline_error', error_type=type(error).__name__, error=str(error))
        write(ledger/case/'summary.json', result)
        return result

    def execute_worker(result):
        case = result['case']
        while args.execution_gate and not args.execution_gate.exists():
            time.sleep(2)
        try:
            result['stages']['run'] = stage(case, 'run', 'scripts/execute_relational_gap_v7.py',
                ['run', '--input', result['emitted'], '--output', result['executed'], '--workers', '1', '--registry', str(args.registry)])
            result['status'] = 'complete'
        except Exception as error:
            result.update(status='pipeline_error', error_type=type(error).__name__, error=str(error))
        write(ledger/case/'summary.json', result)
        return result

    summaries = []
    def finished(result):
        summaries.append(result)
        write(ledger/'summary.json', summaries)
        print(json.dumps({'case': result['case'], 'status': result['status']}), flush=True)
    with ThreadPoolExecutor(max_workers=2) as executions:
        run_futures = []
        with ThreadPoolExecutor(max_workers=4) as preparations:
            futures = [preparations.submit(prepare_worker, case) for case in cases]
            for future in as_completed(futures):
                result = future.result()
                if result['status'] == 'ready_for_execution':
                    run_futures.append(executions.submit(execute_worker, result))
                else:
                    finished(result)
        print(json.dumps({'preparation_complete': True, 'execution_cases': len(run_futures)}), flush=True)
        for future in as_completed(run_futures):
            finished(future.result())
    runs = []
    for case in cases:
        path = Path(str(args.prefix)+'_runs')/case/'runs.json'
        if path.exists():
            runs.extend(read(path))
    write(ledger/'runs.json', runs)
    print(json.dumps({'finished_cases': len(summaries), 'runs': len(runs), 'provider_calls': 0}), flush=True)


if __name__ == '__main__':
    main()
