"""Freeze a paired component experiment using identical historical source evidence.

The source manifest selects a regression cohort, not production candidates.
Only frozen source request fields enter the provider. Outcomes remain component
judgments; this runner makes no native-detection or precision claim.
"""
from __future__ import annotations

import argparse
import copy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from relation_search import compact_admission, ledger_admission, counterfactual_admission
from relational_gap.provider import dispatch


def read(path):
    return json.loads(Path(path).read_text())


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write('\n')


def now():
    return datetime.now(timezone.utc)


def identity(request):
    fields = {key: request[key] for key in
              ('system', 'prompt', 'max_tokens', 'thinking', 'reasoning_effort') if key in request}
    return hashlib.sha256(json.dumps(fields, ensure_ascii=False,
        sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def freeze(args):
    source = read(args.input)
    if source['method'] != 'compact':
        raise ValueError('The paired source must use compact requests')
    output = args.output
    output.mkdir(parents=True, exist_ok=False)
    entries = []
    for item in source['items']:
        if not item['request_path']:
            raise ValueError('Paired cohort contains an unprepared request')
        if sha(item['request_path']) != item['request_sha256']:
            raise ValueError('Historical source request changed')
        original = read(item['request_path'])
        for arm in args.arms:
            request = copy.deepcopy(original)
            request.update(thinking=args.thinking, max_tokens=args.output_tokens,
                           reasoning_effort=args.reasoning_effort)
            if arm in {'ledger', 'counterfactual'}:
                method = ledger_admission if arm == 'ledger' else counterfactual_admission
                kwargs = dict(max_output_tokens=args.output_tokens)
                if arm == 'ledger':
                    kwargs['thinking'] = args.thinking
                request = method.from_compact_request(request, **kwargs)
                if request is None:
                    raise ValueError('Paired ledger exceeds the frozen prompt budget')
                request.update(thinking=args.thinking,reasoning_effort=args.reasoning_effort)
            request['id'] = request['query_sha256'] = identity(request)
            name = f'item_{len(entries):04d}'
            path = output / name / 'request.json'
            write(path, request)
            entries.append(dict(name=name, arm=arm, case=item['case'], key=item['key'],
                candidate_id=item['candidate_id'], source_request_sha256=item['request_sha256'],
                request_sha256=sha(path)))
    modules = [Path(__file__), Path(compact_admission.__file__),
               Path(ledger_admission.__file__),Path(counterfactual_admission.__file__),
               ROOT/'relational_gap/provider.py']
    prepared = dict(version='paired-contract-ledger-component.v1', created_utc=now().isoformat(),
        source=dict(path=str(args.input.resolve()), sha256=sha(args.input)),
        entries=entries, algorithm={str(path.resolve()): sha(path) for path in modules},
        max_calls=args.max_calls, max_total_tokens=args.max_total_tokens,
        deadline_utc=args.deadline_utc, source_context_held_constant=True,
        native_executions=0, provider_responses_reused=False, component_only=True)
    write(output/'prepared.json', prepared)
    write(output/'seal.json', dict(prepared_sha256=sha(output/'prepared.json')))
    return dict(paired_candidates=len(source['items']), requests=len(entries))


def run(args):
    import fcntl
    output = args.input
    with (output/'.run.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        prepared = read(output/'prepared.json')
        if sha(output/'prepared.json') != read(output/'seal.json')['prepared_sha256']:
            raise ValueError('Prepared experiment changed')
        for path, expected in prepared['algorithm'].items():
            if sha(path) != expected:
                raise ValueError('Frozen algorithm changed: ' + path)
        deadline = datetime.fromisoformat(prepared['deadline_utc'].replace('Z', '+00:00'))
        results, calls, accounted = [], 0, 0
        for item in prepared['entries']:
            directory = output/item['name']
            path = directory/'request.json'
            if sha(path) != item['request_sha256']:
                raise ValueError('Frozen request changed')
            request = read(path)
            # UTF-8 bytes plus maximum completion is a conservative bound.
            reservation = len(request['system'].encode()) + len(request['prompt'].encode()) + request['max_tokens'] + 1024
            receipt_path = directory/'completion/manifest.json'
            if receipt_path.exists():
                receipt = read(receipt_path)
                if receipt['status'] in {'prepared', 'dispatching'}:
                    raise ValueError('Interrupted dispatch needs process audit; never silently retry')
            else:
                if (calls >= prepared['max_calls'] or accounted + reservation > prepared['max_total_tokens']
                        or (deadline-now()).total_seconds() < 300):
                    break
                receipt = dispatch(request, directory/'completion', root=ROOT)
            calls += receipt['external_model_calls']
            usage = receipt.get('usage') or {}
            tokens = usage.get('total_tokens')
            measured = type(tokens) is int and tokens >= 0
            accounted += tokens if measured else reservation
            method = {'compact':compact_admission,'ledger':ledger_admission,
                      'counterfactual':counterfactual_admission}[item['arm']]
            if receipt['status'] == 'complete':
                result = method.decide(request, (directory/'completion/completion.txt').read_text(),
                                       finish_reason=receipt.get('finish_reason'))
            else:
                result = dict(status='unknown', alarm_eligible=False, reason='provider_error')
            row = dict(**item, decision=result, measured_tokens=tokens if measured else None,
                accounted_tokens=tokens if measured else reservation,
                provider_calls=receipt['external_model_calls'], receipt_sha256=sha(receipt_path))
            if (directory/'decision.json').exists():
                if read(directory/'decision.json') != row:
                    raise ValueError('Recorded decision changed')
            else:
                write(directory/'decision.json', row)
            results.append(row)
            print(json.dumps(dict(case=item['case'], arm=item['arm'], status=result['status'],
                                  calls=calls, accounted_tokens=accounted)), flush=True)
        summary = dict(prepared_sha256=sha(output/'prepared.json'), results=results,
            pending=len(prepared['entries'])-len(results), provider_calls=calls,
            accounted_tokens=accounted, completed_utc=now().isoformat(), component_only=True)
        if not (output/'summary.json').exists():
            write(output/'summary.json', summary)
        return {key: value for key, value in summary.items() if key != 'results'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('stage', choices=['prepare', 'run'])
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--thinking', choices=['enabled', 'disabled'], default='enabled')
    parser.add_argument('--arms',nargs='+',choices=['compact','ledger','counterfactual'],
                        default=['compact','ledger'])
    parser.add_argument('--reasoning-effort', choices=['low', 'high', 'max'], default='low')
    parser.add_argument('--output-tokens', type=int, default=8192)
    parser.add_argument('--max-calls', type=int, default=32)
    parser.add_argument('--max-total-tokens', type=int, default=750000)
    parser.add_argument('--deadline-utc', default='2026-10-04T01:51:21Z')
    options = parser.parse_args()
    print(json.dumps(freeze(options) if options.stage == 'prepare' else run(options)))
