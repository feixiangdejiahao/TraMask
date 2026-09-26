"""Download public failed-trial evidence for the September 26 case study.

This is retrospective discovery, not a blind generation experiment. Public
verifier logs are kept separate from agent-visible trajectory evidence.
No provider credentials or model API are used.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil

import httpx

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "results/expanded_trials_20260926"
TASKS = Path('/home/jhx/oracle_gap/external/deep-swe/tasks')
ARTIFACTS = {'trajectory.json': 'agent/trajectory.json',
             'model.patch': 'artifacts/model.patch',
             'verifier/ctrf.json': 'verifier/ctrf.json',
             'verifier/reward.json': 'verifier/reward.json',
             'verifier/test-stdout.txt': 'verifier/test-stdout.txt'}

def save_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')

def fetch(url, path, *, refresh=False):
    if refresh or not path.exists():
        with httpx.Client(timeout=90, follow_redirects=True) as client:
            r = client.get(url)
            r.raise_for_status()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(r.content)
    b = path.read_bytes()
    return {'url': url, 'path': str(path.relative_to(ROOT)), 'bytes': len(b),
            'sha256': hashlib.sha256(b).hexdigest()}

def refresh_index():
    records = []
    for name in ('trials', 'tasks', 'release'):
        dest = OUT / 'index' / (name + '.json')
        records.append(fetch(f'https://deepswe.datacurve.ai/artifacts/v1.1/{name}.json', dest, refresh=True))
        json.loads(dest.read_text())
    save_json(OUT / 'index' / 'provenance.json', {'retrieved_at': datetime.now(timezone.utc).isoformat(), 'files': records})

def acquire(row):
    trial = row['trial_name']
    dest = OUT / 'trials' / trial
    dest.mkdir(parents=True, exist_ok=True)
    save_json(dest / 'metadata.json', row)
    record = {'trial': trial, 'task': row['task_name'], 'model': row['model'], 'outcome': row['outcome'],
              'trial_url': f'https://deepswe.datacurve.ai/data/v1.1/trials/{trial}', 'artifacts': [], 'errors': []}
    for name, relative in ARTIFACTS.items():
        url = f'https://d3ujjcmjq6o8v6.cloudfront.net/v1.1/trial-artifacts/{trial}/{relative}'
        try:
            record['artifacts'].append(fetch(url, dest / name))
        except (httpx.HTTPError, OSError) as e:
            record['errors'].append({'url': url, 'kind': type(e).__name__, 'message': str(e)})
    for name in ('instruction.md', 'task.toml'):
        source = TASKS / row['task_name'] / name
        if source.exists():
            shutil.copy2(source, dest / name)
            record['artifacts'].append({'path': str((dest/name).relative_to(ROOT)), 'source': str(source),
                                       'sha256': hashlib.sha256(source.read_bytes()).hexdigest()})
    trajectory = dest / 'trajectory.json'
    if trajectory.exists():
        t = json.loads(trajectory.read_text())
        steps = t.get('steps', t.get('messages', []))
        text = []
        for n, step in enumerate(steps):
            text.append(f'\n===== STEP {n}; id={step.get("step_id", n)} =====\n')
            text.append(json.dumps(step, ensure_ascii=False, indent=2))
        (dest / 'trajectory_readable.txt').write_text('\n'.join(text))
    save_json(dest / 'acquisition.json', record)
    return {'trial': trial, 'artifacts': len(record['artifacts']), 'errors': record['errors']}

def main():
    p = argparse.ArgumentParser()
    p.add_argument('--refresh-index', action='store_true')
    p.add_argument('--tasks', nargs='*', default=[])
    p.add_argument('--trials', nargs='*', default=[])
    p.add_argument('--per-task', type=int, default=1)
    args = p.parse_args()
    if args.refresh_index:
        refresh_index()
    if not args.tasks and not args.trials:
        return
    rows = json.loads((OUT/'index/trials.json').read_text())['rows']
    rows = [r for r in rows if r.get('model') == 'deepseek-v4-flash' and r.get('outcome') == 'fail'
            and r.get('source') == 'deep-swe' and r.get('has_trajectory') and r.get('has_model_patch')]
    selected = [r for r in rows if r['trial_name'] in args.trials]
    for task in args.tasks:
        candidates = sorted((r for r in rows if r['task_name'] == task), key=lambda r: r['trial_name'])
        selected.extend(candidates[:args.per_task])
    selected = list({r['trial_name']: r for r in selected}.values())
    with ThreadPoolExecutor(max_workers=5) as executor:
        for result in executor.map(acquire, selected):
            print(json.dumps(result), flush=True)

if __name__ == '__main__':
    main()
