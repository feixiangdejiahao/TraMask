"""Acquire the complete failed DeepSWE cohort for manual trajectory reading.

Only public trajectories, submitted patches and task instructions are acquired.
No model calls, verifier tests, reference solutions or subject runs occur here.
Existing downloaded evidence is copied with receipts instead of overwritten.
"""
from __future__ import annotations
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import time
import tomllib

import httpx

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / 'results/deepswe_failure_manual_20261006'
TASKS = Path('/home/jhx/oracle_gap/external/deep-swe/tasks')
OLD = ROOT / 'results/expanded_trials_20260926/trials'


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def receipt(path):
    return dict(path=str(path.resolve()), bytes=path.stat().st_size,
                sha256=hashlib.sha256(path.read_bytes()).hexdigest())


def acquire(row, output):
    directory = output / 'trials' / row['trial_name']
    directory.mkdir(parents=True, exist_ok=True)
    write(directory / 'metadata.json', row)
    record = dict(trial=row['trial_name'], task=row['task_name'], model=row['model'],
                  outcome=row['outcome'], artifacts=[], errors=[], refreshed_utc=datetime.now(timezone.utc).isoformat())
    for name, suffix in [('trajectory.json', 'agent/trajectory.json'), ('model.patch', 'artifacts/model.patch')]:
        path = directory / name
        url = f"https://d3ujjcmjq6o8v6.cloudfront.net/v1.1/trial-artifacts/{row['trial_name']}/{suffix}"
        attempts = []
        cached = OLD / row['trial_name'] / name
        origin = 'previous_public_download'
        if not path.exists():
            if cached.is_file():
                shutil.copy2(cached, path)
            else:
                origin = 'public_download'
                for n in range(1, 4):
                    try:
                        with httpx.Client(timeout=120, follow_redirects=True) as client:
                            response = client.get(url)
                            response.raise_for_status()
                        path.write_bytes(response.content)
                        attempts.append(dict(attempt=n, status=response.status_code, bytes=len(response.content)))
                        break
                    except httpx.HTTPError as error:
                        attempts.append(dict(attempt=n, error=type(error).__name__))
                        if n != 3:
                            time.sleep(1)
        else:
            origin = 'resume_existing_public_download'
        if path.exists():
            item = dict(name=name, url=url, origin=origin, attempts=attempts, **receipt(path))
            if cached.is_file():
                item['previous_receipt'] = receipt(cached)
                if item['sha256'] != item['previous_receipt']['sha256']:
                    record['errors'].append(dict(name=name, error='cached_content_changed'))
            record['artifacts'].append(item)
        else:
            record['errors'].append(dict(name=name, url=url, attempts=attempts, error='unavailable'))
    for name in ['instruction.md', 'task.toml']:
        source = TASKS / row['task_name'] / name
        target = directory / name
        if source.exists():
            shutil.copy2(source, target)
            record['artifacts'].append(dict(name=name, origin='local_original_task', source=receipt(source), **receipt(target)))
        else:
            record['errors'].append(dict(name=name, error='task_source_missing'))
    trajectory = directory / 'trajectory.json'
    if trajectory.exists():
        try:
            document = json.loads(trajectory.read_text())
            record.update(trajectory_steps=len(document['steps']), trajectory_agent=document.get('agent'),
                          step_ids=[s.get('step_id') for s in document['steps']])
        except (ValueError, KeyError) as error:
            record['errors'].append(dict(name='trajectory.json', error=type(error).__name__))
    if (directory / 'task.toml').exists():
        record['language'] = tomllib.loads((directory / 'task.toml').read_text())['metadata']['language']
    record['ready_for_reading'] = not record['errors']
    write(directory / 'acquisition.json', record)
    return dict(trial=row['trial_name'], language=record.get('language'), ready=record['ready_for_reading'],
                steps=record.get('trajectory_steps'), errors=record['errors'])


def run(index, output, workers):
    rows = [r for r in json.loads(index.read_text())['rows'] if r.get('source') == 'deep-swe'
            and r.get('model') == 'deepseek-v4-flash' and r.get('outcome') == 'fail']
    if len({r['trial_name'] for r in rows}) != len(rows):
        raise ValueError('duplicate_trial_identity')
    write(output / 'acquisition_protocol.json', dict(index=receipt(index), trials=len(rows), tasks=len({r['task_name'] for r in rows}),
          source='deep-swe', model='deepseek-v4-flash', outcome='fail', all_failure_rows_included=True,
          excluded_artifacts=['hidden verifier tests', 'reference solution', 'generated research tests'], model_calls=0))
    complete = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(acquire, row, output): row for row in rows}
        for future in as_completed(futures):
            row = future.result(); complete.append(row)
            print(json.dumps(row, ensure_ascii=False), flush=True)
    summary = dict(expected=len(rows), ready=sum(r['ready'] for r in complete),
                   rows=sorted(complete, key=lambda r:r['trial']), model_calls=0)
    write(output / 'acquisition_summary.json', summary)
    return {k:v for k,v in summary.items() if k != 'rows'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('--index', type=Path, default=ROOT / 'results/expanded_trials_20260926/index/trials.json')
    parser.add_argument('--output', type=Path, default=OUTPUT)
    parser.add_argument('--workers', type=int, default=8)
    args = parser.parse_args()
    print(json.dumps(run(args.index, args.output, args.workers)))
