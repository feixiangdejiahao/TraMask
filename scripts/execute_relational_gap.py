"""Semantic admission and concrete execution of frozen relational proposals."""
from __future__ import annotations

import argparse
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from relational_gap.provider import dispatch, encoded
from relational_gap.semantics import prepare_requests, validate_response, SemanticBudget


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(encoded(value))


def load(path):
    return json.loads(path.read_text())


def frozen(directory):
    manifest = load(directory/'prepare.json')
    for name, sha in manifest['files_sha256'].items():
        if hashlib.sha256((directory/name).read_bytes()).hexdigest() != sha:
            raise ValueError('Frozen input modified: ' + name)
    return manifest


def requests(args):
    frozen(args.input)
    args.output.mkdir(parents=True, exist_ok=False)
    corpus = load(args.input/'corpus.json')
    frontend = load(args.input/'frontend.json')
    candidates = load(args.input/'candidates.json')['candidates']
    protocol = {'version': 1, 'input': str(args.input.resolve()), 'model': 'deepseek-v4-flash',
                'semantic_budget': SemanticBudget().__dict__, 'max_output_tokens': 16384,
                'temperature': 0, 'source_program_generated_candidates_only': True,
                'target_labels_reference_or_execution_inputs': False,
                'algorithm_hashes': {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                                     for p in [*ROOT.glob('relational_gap/*.py'), Path(__file__)]}}
    write(args.output/'protocol.json', protocol)
    result = prepare_requests(corpus, frontend, candidates, (args.input/'issue.md').read_text())
    for req in result.pop('requests'):
        write(args.output/f'request_{req["index"]}.json', req)
    write(args.output/'selection.json', result)
    return {'requests': len(list(args.output.glob('request_*.json'))), 'skipped': len(result['skipped'])}


def complete(args):
    request = load(args.input/f'request_{args.index}.json')
    manifest = dispatch(request, args.output, root=ROOT)
    if manifest['status'] != 'complete':
        return manifest
    protocol = load(args.input/'protocol.json')
    corpus = load(Path(protocol['input'])/'corpus.json')
    validation = validate_response(request, (args.output/'completion.txt').read_text(), corpus=corpus)
    write(args.output/'validation.json', validation)
    return {'status': manifest['status'], 'accepted': len(validation['accepted']),
            'unknown': len(validation['unknown']), 'rejected': len(validation['rejected']),
            'protocol_error': validation.get('protocol_error'), 'usage': manifest.get('usage')}


def emit_batch(args):
    from generic_composition.emitter import emit
    from generic_composition.runner import infer_harness
    frozen(args.input)
    args.output.mkdir(parents=True, exist_ok=False)
    case = load(args.input/'case.json')
    corpus = load(args.input/'corpus.json')
    candidates = []
    for result in args.completions:
        candidates.extend(load(result/'validation.json')['accepted'])
    unique = {candidate['id']: candidate for candidate in candidates}
    write(args.output/'accepted.json', list(unique.values()))
    groups = defaultdict(list)
    for candidate in unique.values():
        groups[corpus['tests'][candidate['base_test_id']]['span']['path']].append(candidate)
    artifacts = []
    for index, (path, members) in enumerate(sorted(groups.items())):
        emitted = emit(corpus, members)
        folder = args.output/f'group_{index:03d}'
        write(folder/'emission.json', emitted)
        if not emitted['obligations']:
            continue
        try:
            harness = infer_harness(Path(case['repository']), case['language'], list(emitted['files']),
                                    name_filter='TestGC_' if case['language'] == 'go' else 'gc_')
        except ValueError as exc:
            write(folder/'unsupported.json', {'error': str(exc)})
            continue
        files = {**emitted['files'], **harness.get('files', {})}
        mounts = []
        for name, code in files.items():
            destination = folder/'files'/name
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(code)
            mounts.append({'source': str(destination.resolve()), 'target': name,
                           'sha256': hashlib.sha256(destination.read_bytes()).hexdigest()})
        manifest = {'case': case['id'], 'candidate_ids': [c['id'] for c in members],
                    'command': 'export COMBINATION_REPORT_DIR=/replay-logs\n' + harness['command'],
                    'report': {'format': harness['report_format'], 'path': harness['report_path']},
                    'mounts': mounts, 'obligations': emitted['obligations'], 'controls': emitted['controls'],
                    'timeout': args.timeout, 'original_input': str(args.input.resolve())}
        write(folder/'manifest.json', manifest)
        artifacts.append(str(folder.resolve()))
    write(args.output/'artifacts.json', artifacts)
    return {'accepted': len(unique), 'artifacts': len(artifacts)}


def run(args):
    from combination_testing.test_reports import parse_report
    from scripts.run_relational_gap_case import run_case
    args.output.mkdir(parents=True, exist_ok=False)
    artifacts = load(args.input/'artifacts.json')
    def worker(path):
        path = Path(path)
        manifest = load(path/'manifest.json')
        for mount in manifest['mounts']:
            if hashlib.sha256(Path(mount['source']).read_bytes()).hexdigest() != mount['sha256']:
                raise ValueError('Frozen emitted file modified')
        destination = args.output/path.name
        result = run_case(manifest['case'], manifest['command'], mounts=manifest['mounts'],
                          timeout=manifest['timeout'], output=destination, registry=args.registry)
        names = [x['id'] for x in manifest['obligations']+manifest['controls']]
        normalized = parse_report(destination, manifest['report'], result, selected_names=names)
        write(destination/'normalized.json', normalized)
        rows = []
        for item in manifest['obligations']+manifest['controls']:
            rows.append({'case': manifest['case'], 'candidate_id': item.get('candidate_id'),
                         'base_test_id': item['base_test_id'], 'role': 'control' if item['is_control'] else 'generated',
                         'test_ids': [item['id']], 'control_ids': item.get('control_ids', []),
                         'result': str((destination/'normalized.json').resolve()),
                         'manifest': str((path/'manifest.json').resolve())})
        return rows, normalized
    runs, summary = [], []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(worker, artifact): artifact for artifact in artifacts}
        for future in as_completed(futures):
            artifact = futures[future]
            try:
                rows, result = future.result()
                runs.extend(rows)
                summary.append({'artifact': artifact, 'status': result['status'], 'counts': result['counts'], 'errors': result['errors']})
            except Exception as exc:
                summary.append({'artifact': artifact, 'status': 'error', 'error_type': type(exc).__name__})
            write(args.output/'runs.json', runs)
            write(args.output/'summary.json', summary)
            print(json.dumps(summary[-1]), flush=True)
    return {'artifacts': len(artifacts), 'outcomes': summary}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('stage', choices=['requests', 'complete', 'emit', 'run'])
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--index', type=int, default=0)
    parser.add_argument('--completions', type=Path, nargs='*', default=[])
    parser.add_argument('--timeout', type=int, default=240)
    parser.add_argument('--workers', type=int, default=2)
    parser.add_argument('--registry', type=Path, default=ROOT/'data/relational_gap_v1/registry.json')
    args = parser.parse_args()
    result = {'requests': requests, 'complete': complete, 'emit': emit_batch, 'run': run}[args.stage](args)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
