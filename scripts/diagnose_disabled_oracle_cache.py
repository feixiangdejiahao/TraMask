"""Bounded provider diagnostic over a frozen, outcome-independent request list."""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import sys
import time
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from relation_search.checkpoint import digest, read, write


def prompt_identity(request):
    return hashlib.sha256(json.dumps([request['system'], request['prompt']],
        ensure_ascii=True, separators=(',', ':')).encode()).hexdigest()


def prepare(cache, output):
    output.mkdir(parents=True, exist_ok=False)
    unique, all_records = {}, []
    # Every record enters the inventory. No status, revision or verdict field is
    # read for selection; lexicographic prompt SHA fixes the dispatch order.
    for index, record in enumerate(read(cache)['records']):
        original = Path(record['request'])
        request = read(original)
        checksum = digest(original)
        if checksum != record['request_sha256']:
            raise ValueError('Original request checksum changed')
        identity = prompt_identity(request)
        row = dict(record_index=index, source_request=str(original.resolve()),
                   source_request_sha256=checksum, prompt_system_sha256=identity,
                   historical_completion=record['completion'])
        all_records.append(row)
        unique.setdefault(identity, (row, request))
    selected = []
    for index, identity in enumerate(sorted(unique)[:32]):
        row, request = unique[identity]
        original_copy = output/'original_requests'/f'request_{index:03d}.json'
        original_copy.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(row['source_request'], original_copy)
        changed = {**request, 'thinking': 'disabled'}
        new_path = output/'requests'/f'request_{index:03d}.json'
        write(new_path, changed)
        corpus = Path(request['source_prepared'])/'corpus.json'
        historical_payload = Path(row['historical_completion'])/'request.json'
        old_payload = read(historical_payload)
        expected_payload = dict(model='deepseek-v4-flash', temperature=0,
            max_tokens=16384, messages=[dict(role='system', content=request['system']),
            dict(role='user', content=request['prompt'])],
            response_format={'type':'json_object'}, stream=False,
            thinking={'type':'disabled'})
        if {**old_payload, 'thinking': {'type':'disabled'}} != expected_payload:
            raise ValueError('Historical payload differs beyond thinking')
        selected.append(dict(**row, index=index, request=str(new_path.resolve()),
            request_sha256=digest(new_path), original_copy=str(original_copy.resolve()),
            original_copy_sha256=digest(original_copy),
            source_corpus=str(corpus.resolve()), source_corpus_sha256=digest(corpus),
            old_payload_sha256=digest(historical_payload),
            old_payload_thinking=old_payload['thinking']['type'],
            request_id=request['id'], offered_candidates=len(request.get('offered', {}))))
    files = [ROOT/'relational_gap/provider.py', ROOT/'relation_search/oracle.py',
             ROOT/'scripts/relation_search_semantics.py', Path(__file__).resolve()]
    code = {}
    for source in files:
        relative = source.relative_to(ROOT)
        destination = output/'algorithm_snapshot'/relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
        code[str(relative)] = digest(source)
    protocol = dict(version=1, status='frozen_before_dispatch',
        created_at=datetime.now(timezone.utc).isoformat(), cache=str(cache.resolve()),
        cache_sha256=digest(cache), all_records=all_records, requests=selected,
        selection='all records; deduplicate by exact system+prompt; ascending SHA256; maximum 32',
        selected_without_outcomes=True, model='deepseek-v4-flash', provider='existing .env loader',
        changed_parameter={'thinking':'disabled'}, concurrency=1,
        launch_window_seconds=360, retries=0, correctness_evaluated=False,
        code_sha256=code)
    write(output/'protocol.json', protocol)
    write(output/'protocol.seal.json', dict(sha256=digest(output/'protocol.json')))
    return dict(records=len(all_records), distinct=len(unique), selected=len(selected),
                protocol_sha256=digest(output/'protocol.json'))


def summarize(output, rows, elapsed, finished=False):
    counts = Counter()
    tokens = Counter()
    for row in rows:
        counts['launched'] += 1
        counts['completed'] += row['provider_completed']
        counts['json_valid'] += row['json_valid']
        counts['guard_accepted_revisions'] += row['guard_accepted_revisions']
        counts['with_accepted_revisions'] += bool(row['guard_accepted_revisions'])
        for key, value in (row.get('usage') or {}).items():
            if type(value) is int:
                tokens[key] += value
            elif isinstance(value, dict):
                for nested, amount in value.items():
                    if type(amount) is int:
                        tokens[key+'.'+nested] += amount
    summary = dict(finished=finished, counts=dict(counts), tokens=dict(tokens),
        completion_rate=counts['completed']/len(rows) if rows else None,
        strict_json_valid_rate=counts['json_valid']/len(rows) if rows else None,
        elapsed_seconds=elapsed, correctness_evaluated=False, records=rows)
    write(output/'diagnostic.json', summary)
    return summary


def run(output):
    from scripts.relation_search_semantics import complete
    protocol_path = output/'protocol.json'
    if digest(protocol_path) != read(output/'protocol.seal.json')['sha256']:
        raise ValueError('Protocol changed')
    protocol = read(protocol_path)
    for relative, checksum in protocol['code_sha256'].items():
        if digest(ROOT/relative) != checksum:
            raise ValueError('Diagnostic code changed')
    if (output/'launch.json').exists():
        raise ValueError('A launched diagnostic is not silently restarted')
    write(output/'launch.json', dict(started_at=datetime.now(timezone.utc).isoformat(),
                                   protocol_sha256=digest(protocol_path)))
    started, rows = time.monotonic(), []
    for request in protocol['requests']:
        # Check immediately before dispatch. An in-flight call may finish after
        # the six-minute launch window, using the existing provider timeout.
        if time.monotonic()-started >= protocol['launch_window_seconds']:
            break
        path = Path(request['request'])
        if digest(path) != request['request_sha256'] or digest(request['source_corpus']) != request['source_corpus_sha256']:
            raise ValueError('Frozen request or source corpus changed')
        destination = output/'completions'/path.stem
        launched = time.monotonic()-started
        error = None
        try:
            complete(SimpleNamespace(input=path, output=destination))
        except Exception as exc:
            error = type(exc).__name__  # Never record exceptions containing URLs.
        manifest_path = destination/'manifest.json'
        manifest = read(manifest_path) if manifest_path.exists() else {}
        completion = destination/'completion.txt'
        json_valid = False
        if completion.exists():
            try:
                json.loads(completion.read_text())
                json_valid = True
            except (ValueError, UnicodeError):
                pass
        validation_path = destination/'validation.json'
        validation = read(validation_path) if validation_path.exists() else {}
        row = dict(index=request['index'], request_id=request['request_id'],
            request=request['request'], completion=str(destination.resolve()),
            launch_seconds=launched, provider_completed=manifest.get('status')=='complete',
            status=manifest.get('status', 'local_error'), json_valid=json_valid,
            guard_accepted_revisions=len(validation.get('revisions', [])),
            validation_error=validation.get('error'), local_error=error,
            usage=manifest.get('usage'), provider_seconds=manifest.get('seconds'),
            elapsed_seconds=time.monotonic()-started-launched,
            files_sha256={p.name:digest(p) for p in destination.iterdir() if p.is_file()}
                         if destination.exists() else {})
        rows.append(row)
        summarize(output, rows, time.monotonic()-started)
        print(json.dumps({k:row[k] for k in ['index','status','json_valid',
              'guard_accepted_revisions','elapsed_seconds']}), flush=True)
    return summarize(output, rows, time.monotonic()-started, finished=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('stage', choices=['prepare','run'])
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--cache', type=Path)
    args = parser.parse_args()
    result = prepare(args.cache, args.output) if args.stage=='prepare' else run(args.output)
    print(json.dumps({k:v for k,v in result.items() if k!='records'}), flush=True)
