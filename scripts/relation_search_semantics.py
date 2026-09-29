"""Prepare and cache the optional local assertion-interpretation stage."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def read(path):
    return json.loads(path.read_text())


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True, indent=2)+'\n')


def prepare(args):
    from relation_search.oracle import prepare_requests
    from scripts.execute_relation_search import frozen
    frozen(args.input)
    corpus = read(args.input/'corpus.json')
    frontend = read(args.input/'frontend.json')
    candidates = read(args.input/'candidates.json')['candidates']
    requests = prepare_requests(corpus, frontend, candidates, (args.input/'issue.md').read_text(),
                                args.requests, args.per_request)
    args.output.mkdir(parents=True, exist_ok=False)
    for index, request in enumerate(requests):
        request['source_prepared'] = str(args.input.resolve())
        write(args.output/f'request_{index:03d}.json', request)
    write(args.output/'protocol.json', dict(source=str(args.input.resolve()), model='deepseek-v4-flash',
                                           requests=len(requests), input_candidates=len(candidates),
                                           request_sha256={p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                                                           for p in args.output.glob('request_*.json')},
                                           generator_sha256=hashlib.sha256((ROOT/'relation_search/oracle.py').read_bytes()).hexdigest()))
    return dict(requests=len(requests), candidates=len(candidates))


def complete(args):
    from relational_gap.provider import dispatch
    from relation_search.oracle import validate
    request = read(args.input)
    record = dispatch(request, args.output, root=ROOT)
    if record['status'] != 'complete':
        return dict(status=record['status'], error_type=record.get('error_type'))
    corpus = read(Path(request['source_prepared'])/'corpus.json')
    try:
        result = validate(request, (args.output/'completion.txt').read_text(), corpus)
    except (ValueError, TypeError, KeyError) as error:
        result = dict(revisions=[], decisions=[], error=type(error).__name__)
    write(args.output/'validation.json', result)
    return dict(status=record['status'], revised=len(result['revisions']),
                judged=len(result['decisions']), error=result.get('error'), usage=record.get('usage'))


def merge(args):
    from scripts.execute_relation_search import frozen
    frozen(args.input)
    args.output.mkdir(parents=True, exist_ok=False)
    original = read(args.input/'candidates.json')['candidates']
    revisions, responses = [], []
    for directory in args.completions:
        manifest = read(directory/'manifest.json')
        if manifest['status'] != 'complete' or not (directory/'validation.json').exists():
            continue
        outcome = read(directory/'validation.json')
        revisions.extend(outcome['revisions'])
        responses.append(dict(path=str(directory.resolve()), request_id=manifest['request_id'],
                              response_sha256=manifest.get('response_sha256')))
    originals = {row['id'] for row in original}
    if any(row.get('semantic_revision', {}).get('parent') not in originals for row in revisions):
        raise ValueError('revision parent absent from prepared source candidates')
    for path in args.input.iterdir():
        if path.is_file() and path.name not in {'prepare.json', 'candidates.json', 'checkpoint.json', 'stage.json'}:
            (args.output/path.name).symlink_to(path.resolve())
    # Model omissions never remove the original program-generated hypothesis.
    write(args.output/'candidates.json', dict(candidates=[*original, *revisions],
                                             source_count=len(original), semantic_count=len(revisions),
                                             recorded_responses=responses))
    write(args.output/'prepare.json', dict(status='prepared',
                case=read(args.input/'case.json')['id'], source_prepare=str((args.input/'prepare.json').resolve()),
                files_sha256={p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                              for p in args.output.iterdir() if p.is_file()},
                model_calls=len(responses), local_oracle_only=True))
    return dict(source=len(original), revisions=len(revisions), retained=len(original)+len(revisions))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('stage', choices=['prepare', 'complete', 'merge'])
    parser.add_argument('--input', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--requests', type=int, default=4)
    parser.add_argument('--per-request', type=int, default=16)
    parser.add_argument('--completions', nargs='*', type=Path, default=[])
    args = parser.parse_args()
    print(json.dumps({'prepare': prepare, 'complete': complete, 'merge': merge}[args.stage](args)))
