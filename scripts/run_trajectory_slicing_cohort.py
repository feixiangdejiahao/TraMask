#!/usr/bin/env python3
"""Replay the fixed 88 trajectories, collect IO, then run the public D/F pipeline.

Each run uses a frozen algorithm package. A failed worker leaves its traceback
and artifacts; the scheduler finishes the other cases without retrying it.
Manual labels are used only by a separate evaluation after these outputs exist.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
COHORT = ROOT / 'results/behavioral_masking/20261026_fragment_reuse_n88_r01/cases.json'


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def worker(out, sid):
    sys.path.insert(0, str(out / 'code/src'))
    from eviweave.collection import collect_tests
    from eviweave.artifacts import relative_references
    from eviweave.replay import load_case
    from eviweave.slicing import slice_targets
    case = next(c for c in json.loads((out / 'cases.json').read_text()) if c['id'] == sid)
    directory = out / 'cases' / sid
    started = time.monotonic()
    protocol=json.loads((out/'protocol.json').read_text());collection_run=protocol['collection_run']
    if collection_run is None:
        write(directory / 'stage.json', {'stage': 'collect', 'started': time.time()})
        result = collect_tests(load_case(sid, case['input_directory']), case['input_directory'], directory / 'replay',
                               shared_chunks=(out/protocol['shared_chunks']).resolve())
    else:
        source=(out/collection_run).resolve()/'cases'/sid/'replay'
        result=json.loads((source/'summary.json').read_text())
        result['step_a']['manifest']=str((source/result['step_a']['manifest']).resolve())
    write(directory / 'stage.json', {'stage': 'slice', 'submission_state_matches': result['state_validation_passed']})
    if result['state_validation_passed']:
        slices = slice_targets(result['step_a']['manifest'], directory / 'slicing')
    else:
        slices = None
    summary = {'id': sid, 'language': case['language'], 'trial': case['trial'],
               'submission_state_matches': result['state_validation_passed'],
               'actions': result['actions_executed'], 'timeouts': result['timeouts'],
               'returncode_differences': result['returncode_differences'],
               'slicing': relative_references(slices,directory) if slices is not None else None,
               'wall_seconds': time.monotonic() - started}
    write(directory / 'summary.json', summary)
    write(directory / 'stage.json', {'stage': 'complete'})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--cases', nargs='+')
    parser.add_argument('--workers', type=int, default=12)
    parser.add_argument('--worker')
    parser.add_argument('--collection-run',type=Path,help='Explicit existing collection; run only D/F in this new output')
    parser.add_argument('--shared-chunks',type=Path,help='Share chunks across multiple runs')
    args = parser.parse_args()
    out = args.out.resolve()
    if args.worker:
        worker(out, args.worker)
        return
    out.mkdir(parents=True)
    (out / 'cases').mkdir()
    chunks=args.shared_chunks.resolve() if args.shared_chunks else out/'chunks'
    chunks.mkdir(parents=True,exist_ok=True)
    shutil.copytree(ROOT / 'src/eviweave', out / 'code/src/eviweave', ignore=shutil.ignore_patterns('__pycache__'))
    shutil.copyfile(Path(__file__), out / 'code/runner.py')
    cases = [{'id': c['screen_id'], 'trial': c['trial'], 'language': c['language'],
              'input_directory': c['input_directory']}
             for c in json.loads(COHORT.read_text())['cases']]
    if args.cases:
        assert set(args.cases) <= {c['id'] for c in cases}
        cases = [c for c in cases if c['id'] in args.cases]
    write(out / 'cases.json', cases)
    write(out / 'protocol.json', {'cases': [c['id'] for c in cases], 'workers': args.workers,
                                 'inputs': 'original task/issue/patch/trajectory; no Verifier or manual labels',
                                 'collection_run':os.path.relpath(args.collection_run.resolve(),out) if args.collection_run else None,
                                 'shared_chunks':os.path.relpath(chunks,out),
                                 'code': 'code/src/eviweave', 'new_llm_calls': 0})
    started = time.monotonic()

    def run(case):
        directory = out / 'cases' / case['id']; directory.mkdir()
        with (directory / 'worker.log').open('w') as log:
            process = subprocess.run([sys.executable, str(out / 'code/runner.py'), '--out', str(out), '--worker', case['id']],
                                     stdout=log, stderr=subprocess.STDOUT, env={**os.environ, 'PYTHONUNBUFFERED': '1'})
        result = {'id': case['id'], 'returncode': process.returncode, 'log': str(Path('cases')/case['id']/'worker.log')}
        write(directory / 'worker_result.json', result)
        return result

    results = []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = [pool.submit(run, case) for case in cases]
        for future in as_completed(futures):
            result = future.result(); results.append(result)
            print(result['id'], 'worker_returncode', result['returncode'], 'completed', len(results), '/', len(cases), flush=True)
            write(out / 'progress.json', {'completed': len(results), 'total': len(cases), 'results': results})
    summary = {'cases': len(cases), 'worker_success': sum(r['returncode'] == 0 for r in results),
               'worker_errors': [r['id'] for r in results if r['returncode']],
               'results': sorted(results, key=lambda r: r['id']), 'wall_seconds': time.monotonic() - started,
               'new_llm_calls': 0}
    write(out / 'summary.json', summary)
    return 1 if summary['worker_errors'] else 0


if __name__ == '__main__':
    raise SystemExit(main())
