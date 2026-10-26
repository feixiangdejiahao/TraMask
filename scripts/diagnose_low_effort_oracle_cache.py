"""One bounded, paired low-effort run over the prior frozen 32-request inventory.

Preparation is local. Running requires the user's existing trial/provider
authorization and the coordinator's available single model slot. Historical
responses do not influence inclusion or dispatch order.
"""
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


def wire_payload(request, *, thinking, effort=None):
    payload = dict(model='deepseek-v4-flash', temperature=0, max_tokens=16384,
        messages=[dict(role='system', content=request['system']),
                  dict(role='user', content=request['prompt'])],
        response_format={'type': 'json_object'}, stream=False,
        thinking={'type': thinking})
    if effort is not None:
        payload['reasoning_effort'] = effort
    return payload


def prepare(baseline, output):
    baseline = baseline.resolve()
    old_protocol_path = baseline / 'protocol.json'
    if digest(old_protocol_path) != read(baseline / 'protocol.seal.json')['sha256']:
        raise ValueError('Baseline protocol changed')
    old = read(old_protocol_path)
    scope_path = baseline / 'authorization_scope.json'
    scope = read(scope_path)
    if digest(scope_path) != old['authorization_scope']['proof_sha256']:
        raise ValueError('Baseline scope changed')
    if not scope['all_requests_within_existing_17_trials']:
        raise ValueError('Baseline scope is incomplete')
    if len(old['requests']) != 32:
        raise ValueError('Expected the unchanged 32-request inventory')
    scope_by_index = {item['request_index']: item for item in scope['requests']}
    if set(scope_by_index) != set(range(32)):
        raise ValueError('Authorization does not cover all request indices')
    if not old['selected_without_outcomes']:
        raise ValueError('Original inventory was not outcome independent')
    output.mkdir(parents=True, exist_ok=False)
    selected = []
    for index, row in enumerate(old['requests']):
        if index != row['index']:
            raise ValueError('Original request order changed')
        original = Path(row['original_copy'])
        if digest(original) != row['original_copy_sha256']:
            raise ValueError('Original request changed')
        request = read(original)
        if prompt_identity(request) != row['prompt_system_sha256']:
            raise ValueError('Original prompt changed')
        if digest(row['source_corpus']) != row['source_corpus_sha256']:
            raise ValueError('Original source corpus changed')
        old_payload_path = Path(row['historical_completion']) / 'request.json'
        if digest(old_payload_path) != row['old_payload_sha256']:
            raise ValueError('Historical payload changed')
        old_payload = read(old_payload_path)
        old_thinking = row['old_payload_thinking']
        if old_payload != wire_payload(request, thinking=old_thinking):
            raise ValueError('Historical payload differs beyond planned parameters')
        authorized = scope_by_index[index]
        if not all(authorized['matches_authorized_registry'].values()):
            raise ValueError('Trial does not match authorized registry')
        if digest(authorized['case_path']) != authorized['case_sha256']:
            raise ValueError('Authorized case identity changed')
        original_copy = output / 'original_requests' / f'request_{index:03d}.json'
        original_copy.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(original, original_copy)
        changed = {**request, 'thinking': 'enabled', 'reasoning_effort': 'low'}
        destination = output / 'requests' / f'request_{index:03d}.json'
        write(destination, changed)
        expected = wire_payload(request, thinking='enabled', effort='low')
        expected_path = output / 'expected_wire_payloads' / destination.name
        write(expected_path, expected)
        selected.append(dict(index=index, case=authorized['case'],
            trial=authorized['trial'], request_id=request['id'],
            request=str(destination.resolve()), request_sha256=digest(destination),
            original_copy=str(original_copy.resolve()), original_copy_sha256=digest(original_copy),
            source_corpus=row['source_corpus'], source_corpus_sha256=row['source_corpus_sha256'],
            prompt_system_sha256=row['prompt_system_sha256'],
            historical_completion=row['historical_completion'],
            historical_payload_sha256=row['old_payload_sha256'],
            original_thinking=old_thinking,
            stratum=f'original_{old_thinking}',
            changed_parameters=['reasoning_effort'] if old_thinking == 'enabled'
                else ['thinking', 'reasoning_effort'],
            baseline_disabled_completion=str(baseline / 'completions' / destination.stem),
            expected_wire_payload=str(expected_path.resolve()),
            expected_wire_payload_sha256=digest(expected_path)))
    shutil.copyfile(scope_path, output / 'authorization_scope.json')
    sources = ['relational_gap/provider.py', 'relation_search/oracle.py',
               'prototypes/assertion_operand_guard.py', 'relation_search/checkpoint.py',
               'scripts/relation_search_semantics.py',
               'scripts/diagnose_low_effort_oracle_cache.py']
    code = {}
    for relative in sources:
        source = ROOT / relative
        destination = output / 'algorithm_snapshot' / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
        code[relative] = digest(source)
    protocol = dict(version=1, status='frozen_before_dispatch',
        created_at=datetime.now(timezone.utc).isoformat(),
        baseline_protocol=str(old_protocol_path), baseline_protocol_sha256=digest(old_protocol_path),
        authorization_scope=str((output / 'authorization_scope.json').resolve()),
        authorization_scope_sha256=digest(output / 'authorization_scope.json'),
        user_authorization_quote=scope['user_authorization_quote'],
        earlier_provider_authorization_quote=scope['earlier_provider_authorization_quote'],
        selection='all 32 requests in the existing frozen diagnostic; exact original order',
        selected_without_outcomes=True, requests=selected,
        strata=dict(Counter(row['stratum'] for row in selected)),
        model='deepseek-v4-flash', provider='existing .env loader',
        changed_parameters={'thinking': 'enabled', 'reasoning_effort': 'low'},
        concurrency=1, launch_window_seconds=360, request_timeout_seconds=300,
        request_limit=32, max_output_tokens_per_request=16384,
        total_possible_output_tokens=32 * 16384, retries=0,
        correctness_evaluated=False,
        protocol_references=['https://api-docs.deepseek.com/api/create-chat-completion/'],
        interpretation='JSON availability is not oracle correctness; strata are reported separately. '
            'Comparisons of accepted revisions also require identical validator versions.',
        code_sha256=code)
    write(output / 'protocol.json', protocol)
    write(output / 'protocol.seal.json', dict(sha256=digest(output / 'protocol.json')))
    return dict(requests=len(selected), strata=protocol['strata'],
                protocol_sha256=digest(output / 'protocol.json'), external_model_calls=0)


def counts_for(rows):
    counts, tokens = Counter(), Counter()
    for row in rows:
        counts['launched'] += 1
        counts['completed'] += row['provider_completed']
        counts['json_valid'] += row['json_valid']
        counts['empty_content'] += row['content_chars'] == 0
        counts['length_terminated'] += row['finish_reason'] == 'length'
        counts['guard_accepted_revisions'] += row['guard_accepted_revisions']
        counts['with_accepted_revisions'] += bool(row['guard_accepted_revisions'])
        for key, value in (row.get('usage') or {}).items():
            if type(value) is int:
                tokens[key] += value
            elif isinstance(value, dict):
                for nested, amount in value.items():
                    if type(amount) is int:
                        tokens[key + '.' + nested] += amount
    return dict(counts=dict(counts), tokens=dict(tokens),
        completion_rate=counts['completed'] / len(rows) if rows else None,
        strict_json_valid_rate=counts['json_valid'] / len(rows) if rows else None)


def summarize(output, rows, elapsed, finished=False):
    summary = dict(finished=finished, **counts_for(rows),
        strata={stratum: counts_for([row for row in rows if row['stratum'] == stratum])
                for stratum in ['original_enabled', 'original_disabled']},
        elapsed_seconds=elapsed, correctness_evaluated=False, records=rows)
    write(output / 'diagnostic.json', summary)
    return summary


def run(output):
    from scripts.relation_search_semantics import complete
    protocol_path = output / 'protocol.json'
    if digest(protocol_path) != read(output / 'protocol.seal.json')['sha256']:
        raise ValueError('Protocol changed')
    protocol = read(protocol_path)
    if digest(protocol['authorization_scope']) != protocol['authorization_scope_sha256']:
        raise ValueError('Authorization scope changed')
    for relative, checksum in protocol['code_sha256'].items():
        if digest(ROOT / relative) != checksum:
            raise ValueError('Diagnostic code changed')
    if (output / 'launch.json').exists():
        raise ValueError('A launched diagnostic is not silently restarted')
    write(output / 'launch.json', dict(started_at=datetime.now(timezone.utc).isoformat(),
        protocol_sha256=digest(protocol_path), concurrency=1))
    started, rows = time.monotonic(), []
    for request in protocol['requests']:
        if time.monotonic() - started >= protocol['launch_window_seconds']:
            break
        path = Path(request['request'])
        if digest(path) != request['request_sha256'] or digest(request['source_corpus']) != request['source_corpus_sha256']:
            raise ValueError('Frozen request or source corpus changed')
        destination = output / 'completions' / path.stem
        launched, error = time.monotonic() - started, None
        try:
            complete(SimpleNamespace(input=path, output=destination))
        except Exception as exc:
            error = type(exc).__name__
        manifest = read(destination / 'manifest.json') if (destination / 'manifest.json').exists() else {}
        completion = destination / 'completion.txt'
        json_valid, content_chars = False, None
        if completion.exists():
            content = completion.read_text()
            content_chars = len(content)
            try:
                json.loads(content)
                json_valid = True
            except (ValueError, UnicodeError):
                pass
        validation_path = destination / 'validation.json'
        validation = read(validation_path) if validation_path.exists() else {}
        actual_payload = destination / 'request.json'
        expected_path = Path(request['expected_wire_payload'])
        wire_matches = (actual_payload.exists() and
            digest(expected_path) == request['expected_wire_payload_sha256'] and
            read(actual_payload) == read(expected_path))
        row = dict(index=request['index'], request_id=request['request_id'],
            case=request['case'], stratum=request['stratum'],
            request=request['request'], completion=str(destination.resolve()),
            launch_seconds=launched, provider_completed=manifest.get('status') == 'complete',
            status=manifest.get('status', 'local_error'), json_valid=json_valid,
            content_chars=content_chars, finish_reason=manifest.get('finish_reason'),
            guard_accepted_revisions=len(validation.get('revisions', [])),
            validation_error=validation.get('error'), local_error=error,
            usage=manifest.get('usage'), provider_seconds=manifest.get('seconds'),
            elapsed_seconds=time.monotonic() - started - launched,
            expected_wire_payload_matches=wire_matches,
            files_sha256={p.name: digest(p) for p in destination.iterdir() if p.is_file()}
                         if destination.exists() else {})
        rows.append(row)
        summarize(output, rows, time.monotonic() - started)
        print(json.dumps({key: row[key] for key in ['index', 'case', 'stratum', 'status',
            'json_valid', 'guard_accepted_revisions', 'elapsed_seconds']}), flush=True)
        if not wire_matches:
            raise ValueError('Wire payload differed from frozen expected request')
    result = summarize(output, rows, time.monotonic() - started, finished=True)
    write(output / 'diagnostic.seal.json', dict(sha256=digest(output / 'diagnostic.json')))
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('stage', choices=['prepare', 'run'])
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--baseline', type=Path)
    args = parser.parse_args()
    result = prepare(args.baseline, args.output) if args.stage == 'prepare' else run(args.output)
    print(json.dumps({key: value for key, value in result.items() if key != 'records'}), flush=True)
