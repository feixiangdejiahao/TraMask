"""Run retrieval on local pilot inputs. This module does not read target labels."""
from __future__ import annotations

import argparse
import gc
import hashlib
import json
import shutil
import subprocess
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path

from .retrieve import retrieve

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cases', nargs='+', default=['P1', 'P2', 'P3', 'P4', 'P5', 'P6', 'P7'])
    parser.add_argument('--output', type=Path, default=ROOT / 'results/anchor_retrieval/run1')
    parser.add_argument('--repository-only', action='store_true')
    args = parser.parse_args()
    policy = json.loads((ROOT / 'configs/execution_policy.json').read_text())
    if not policy['allow_experiment_execution']:
        parser.error('Local execution policy does not authorize experiments.')
    args.output.mkdir(parents=True, exist_ok=True)
    manifest = {'started_at': datetime.now(timezone.utc).isoformat(), 'python': sys.version,
                'inputs': ['candidate repository', 'candidate patch', 'trajectory tool arguments'],
                'code_sha256': {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                                for p in sorted((ROOT / 'anchor_retrieval').glob('*.py'))},
                'cases': args.cases, 'repository_only': args.repository_only,
                'external_model_calls': 0, 'target_labels_read_by_retriever': False}
    revision = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=ROOT, capture_output=True, text=True)
    status = subprocess.run(['git', 'status', '--porcelain', '--untracked-files=no'], cwd=ROOT,
                            capture_output=True, text=True)
    manifest['git_commit'] = revision.stdout.strip() if revision.returncode == 0 else None
    manifest['git_tracked_changes'] = status.stdout.splitlines() if status.returncode == 0 else None
    (args.output / 'manifest.json').write_text(json.dumps(manifest, indent=2))
    snapshot = args.output / 'implementation_snapshot'
    snapshot.mkdir(exist_ok=True)
    for path in (ROOT / 'anchor_retrieval').glob('*.py'):
        shutil.copy2(path, snapshot / path.name)
    registry = {c['id']: c for c in json.loads((ROOT / 'data/cases.json').read_text())}
    failed = []
    for cid in args.cases:
        base = ROOT / 'data/cases' / cid
        print(f'{cid}: retrieval started', flush=True)
        try:
            result = retrieve(base / 'repository', base / 'model.patch', registry[cid]['language'],
                              None if args.repository_only else base / 'trajectory.json')
            (args.output / f'{cid}.json').write_text(json.dumps(result, ensure_ascii=True, indent=2))
            (args.output / f'{cid}.selected_tests.json').write_text(json.dumps(result['selected_tests'], ensure_ascii=True, indent=2))
            (args.output / f'{cid}.baseline_selected_tests.json').write_text(json.dumps(result['baseline_selected_tests'], ensure_ascii=True, indent=2))
            print(json.dumps({'case': cid, 'counts': result['counts'], 'timing': result['timing_seconds']}, ensure_ascii=False), flush=True)
            del result
        except Exception:
            failed.append(cid)
            error = traceback.format_exc()
            (args.output / f'{cid}.error.txt').write_text(error)
            print(error, file=sys.stderr, flush=True)
        gc.collect()
    manifest['finished_at'] = datetime.now(timezone.utc).isoformat()
    manifest['failed_cases'] = failed
    (args.output / 'manifest.json').write_text(json.dumps(manifest, indent=2))
    raise SystemExit(bool(failed))


if __name__ == '__main__':
    main()
