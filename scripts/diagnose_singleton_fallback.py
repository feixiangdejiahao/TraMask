"""Bounded thinking-disabled retry of completed, non-JSON singleton replies."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict, deque
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


def strict_json(path):
    def invalid_constant(value):
        raise ValueError('Non-JSON numeric constant')
    try:
        json.loads(path.read_text(), parse_constant=invalid_constant)
        return True
    except (ValueError, UnicodeError, FileNotFoundError):
        return False


def prompt_identity(request):
    return hashlib.sha256(json.dumps([request['system'], request['prompt']],
        ensure_ascii=True, separators=(',', ':')).encode()).hexdigest()


def prepare(campaigns, output):
    output.mkdir(parents=True, exist_ok=False)
    registry_path = ROOT / 'data/relational_gap_v1/registry.json'
    registry = {row['id']: row for row in read(registry_path)}
    expected_ids = {f'P{i}' for i in range(1, 8)} | {f'N{i:02d}' for i in range(1, 11)}
    if set(registry) != expected_ids:
        raise ValueError('Authorized registry differs from the 17-trial scope')
    inventory, unique = [], {}
    # Snapshot request paths before inspecting completion records. Selection
    # reads request count, transport status and JSON syntax only, never a guard
    # decision, target, expected material, review or semantic-cache verdict.
    paths = sorted(path for campaign in campaigns
        for path in campaign.glob('*/round_*/semantic/requests/request_*.json'))
    for path in paths:
        request = read(path)
        directory = path.parent.parent / 'completions' / path.stem
        manifest_path = directory / 'manifest.json'
        manifest = read(manifest_path) if manifest_path.exists() else {}
        offered = len(request.get('offered', {}))
        valid = strict_json(directory / 'completion.txt') if manifest.get('status') == 'complete' else None
        row = dict(source_request=str(path.resolve()), source_request_sha256=digest(path),
            original_completion=str(directory.resolve()), status=manifest.get('status', 'not_completed'),
            offered_count=offered, strict_json_valid=valid,
            eligible=manifest.get('status') == 'complete' and offered == 1 and valid is False)
        inventory.append(row)
        if not row['eligible']:
            continue
        case_path = Path(request['source_prepared']) / 'case.json'
        case = read(case_path)
        if case['id'] not in registry:
            raise ValueError('Source case outside authorized scope')
        expected = registry[case['id']]
        fields = ['trial', 'task', 'base_commit', 'source_roles', 'excluded_roles']
        matches = {key: case.get(key) == expected.get(key) for key in fields}
        if not all(matches.values()):
            raise ValueError('Source case differs from authorized trial')
        if request.get('external_roles') != ['issue', 'source validations', 'program-generated input edits']:
            raise ValueError('Unexpected external data roles')
        if request.get('kind') != 'local_existing_assertion_oracle':
            raise ValueError('Unexpected request role')
        if set(json.loads(request['prompt'])) != {'language', 'issue', 'candidates'}:
            raise ValueError('Unexpected wire data roles')
        corpus = Path(request['source_prepared']) / 'corpus.json'
        identity = prompt_identity(request)
        proof = dict(case=case['id'], trial=case['trial'], case_path=str(case_path.resolve()),
            case_sha256=digest(case_path), matches_authorized_registry=matches,
            source_roles=case['source_roles'], excluded_roles=case['excluded_roles'],
            source_corpus=str(corpus.resolve()), source_corpus_sha256=digest(corpus))
        row.update(case=case['id'], prompt_system_sha256=identity, scope=proof)
        if identity not in unique:
            unique[identity] = (row, request)
        elif (row['case'], row['source_request']) < (unique[identity][0]['case'], unique[identity][0]['source_request']):
            # Some authorized trials share an exact wire prompt. Keep one
            # lexical case/path representative; the full inventory retains
            # every duplicate and its separately checked authorization proof.
            unique[identity] = (row, request)
    queues = defaultdict(deque)
    for identity in sorted(unique):
        queues[unique[identity][0]['case']].append(identity)
    order = []
    while any(queues.values()) and len(order) < 32:
        for case in sorted(queues):
            if queues[case] and len(order) < 32:
                order.append(queues[case].popleft())
    selected = []
    for index, identity in enumerate(order):
        row, request = unique[identity]
        original = output / 'original_requests' / f'request_{index:03d}.json'
        original.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(row['source_request'], original)
        historical = output / 'historical_completions' / f'request_{index:03d}'
        shutil.copytree(row['original_completion'], historical)
        changed = {**request, 'thinking': 'disabled'}
        new_path = output / 'requests' / f'request_{index:03d}.json'
        write(new_path, changed)
        old_payload = read(historical / 'request.json')
        expected = dict(model='deepseek-v4-flash', temperature=0, max_tokens=16384,
            messages=[dict(role='system', content=request['system']),
                      dict(role='user', content=request['prompt'])],
            response_format={'type': 'json_object'}, stream=False, thinking={'type': 'disabled'})
        if 'reasoning_effort' in request:
            expected['reasoning_effort'] = request['reasoning_effort']
        if {**old_payload, 'thinking': {'type': 'disabled'}} != expected:
            raise ValueError('Wire payload would differ beyond thinking')
        selected.append(dict(**row, index=index, request_id=request['id'],
            request=str(new_path.resolve()), request_sha256=digest(new_path),
            original_copy=str(original.resolve()), original_copy_sha256=digest(original),
            historical_copy=str(historical.resolve()),
            historical_copy_sha256={p.name: digest(p) for p in historical.iterdir() if p.is_file()},
            old_thinking=old_payload['thinking']['type']))
    scope = dict(user_authorization_quote='授权本轮全部17个trial',
        earlier_provider_authorization_quote='授权发送到 .env 指定的 provider',
        authorized_registry=str(registry_path), authorized_registry_sha256=digest(registry_path),
        authorized_trials=[dict(case=key, trial=registry[key]['trial']) for key in sorted(registry)],
        selected_scope=[dict(index=row['index'], **row['scope']) for row in selected],
        source_requests_previously_dispatched=True, additional_external_roles=[],
        credentials='Read only by existing .env provider loader; never included in prompts or logs')
    write(output / 'authorization_scope.json', scope)
    sources = [Path(__file__), ROOT / 'scripts/relation_search_semantics.py',
               ROOT / 'relation_search/oracle.py', ROOT / 'relational_gap/provider.py',
               ROOT / 'experimental/assertion_operand_guard.py']
    snapshots = {}
    for source in sources:
        relative = source.relative_to(ROOT)
        destination = output / 'algorithm_snapshot' / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
        snapshots[str(relative)] = digest(source)
    protocol = dict(version=1, frozen_at=datetime.now(timezone.utc).isoformat(),
        status='frozen_before_dispatch', campaigns=[str(p.resolve()) for p in campaigns],
        inventory=inventory, eligible_records=sum(row['eligible'] for row in inventory),
        distinct_eligible=len(unique), selected=len(selected), requests=selected,
        selection='Completed transport plus exactly one offered candidate plus strict JSON syntax invalid; deduplicate exact system+prompt using lexical case/path representative, sort SHA within each case, round-robin lexicographic case IDs; at most 32',
        forbidden_selection_inputs=['target', 'expected', 'review', 'semantic_cache_verdict', 'guard_decisions'],
        changed_parameter={'thinking': 'disabled'}, model='deepseek-v4-flash', provider='existing .env loader',
        concurrency=1, total_provider_concurrency_limit=6, launch_window_seconds=360,
        retries=0, code_sha256=snapshots, authorization_scope_sha256=digest(output / 'authorization_scope.json'),
        correctness_evaluated=False)
    write(output / 'protocol.json', protocol)
    write(output / 'protocol.seal.json', dict(sha256=digest(output / 'protocol.json')))
    return dict(inventory=len(inventory), eligible=protocol['eligible_records'],
        distinct=len(unique), selected=len(selected),
        selected_by_case=dict(Counter(row['case'] for row in selected)),
        protocol_sha256=digest(output / 'protocol.json'))


def summarize(output, records, elapsed, finished=False):
    counts, tokens = Counter(), Counter()
    for row in records:
        counts.update(launched=1, completed=int(row['provider_completed']),
            strict_json_valid=int(row['json_valid']), guard_accepted_revisions=row['guard_accepted_revisions'],
            with_guard_accepted_revisions=int(bool(row['guard_accepted_revisions'])))
        for key, value in (row.get('usage') or {}).items():
            if type(value) is int:
                tokens[key] += value
            elif isinstance(value, dict):
                for nested, amount in value.items():
                    if type(amount) is int:
                        tokens[key + '.' + nested] += amount
    report = dict(finished=finished, elapsed_seconds=elapsed, counts=dict(counts),
        tokens=dict(tokens), records=records, correctness_evaluated=False,
        oracle_review='Independent evaluator required; JSON and local guards are not oracle correctness')
    write(output / 'diagnostic.json', report)
    return report


def run(output):
    from scripts.relation_search_semantics import complete
    protocol = read(output / 'protocol.json')
    if digest(output / 'protocol.json') != read(output / 'protocol.seal.json')['sha256']:
        raise ValueError('Protocol changed')
    if digest(output / 'authorization_scope.json') != protocol['authorization_scope_sha256']:
        raise ValueError('Authorization scope changed')
    for path, checksum in protocol['code_sha256'].items():
        if digest(ROOT / path) != checksum:
            raise ValueError('Frozen diagnostic implementation changed')
    if (output / 'launch.json').exists():
        raise ValueError('Previously launched experiment is not silently restarted')
    concurrency = read(output / 'concurrency_check.json')
    checked = datetime.fromisoformat(concurrency['checked_at'])
    if (datetime.now(timezone.utc) - checked).total_seconds() > 120:
        raise ValueError('Host provider concurrency audit is stale')
    if not 0 <= concurrency['other_provider_concurrency_upper_bound'] <= 5:
        raise ValueError('No provider slot within total limit six')
    write(output / 'launch.json', dict(started_at=datetime.now(timezone.utc).isoformat(),
        concurrency_check_sha256=digest(output / 'concurrency_check.json'),
        protocol_sha256=digest(output / 'protocol.json')))
    started, records = time.monotonic(), []
    for row in protocol['requests']:
        if time.monotonic() - started >= protocol['launch_window_seconds']:
            break
        request = Path(row['request'])
        if digest(request) != row['request_sha256'] or digest(row['scope']['source_corpus']) != row['scope']['source_corpus_sha256']:
            raise ValueError('Frozen request/source changed')
        destination = output / 'completions' / request.stem
        launch_seconds = time.monotonic() - started
        error = None
        try:
            complete(SimpleNamespace(input=request, output=destination))
        except Exception as exc:
            error = type(exc).__name__
        manifest = read(destination / 'manifest.json') if (destination / 'manifest.json').exists() else {}
        validation = read(destination / 'validation.json') if (destination / 'validation.json').exists() else {}
        old_payload = read(Path(row['historical_copy']) / 'request.json')
        new_payload = read(destination / 'request.json') if (destination / 'request.json').exists() else None
        if new_payload is not None and new_payload != {**old_payload, 'thinking': {'type': 'disabled'}}:
            raise ValueError('Actual provider payload differs beyond thinking')
        record = dict(index=row['index'], case=row['case'], request=row['request'],
            completion=str(destination.resolve()), launch_seconds=launch_seconds,
            elapsed_seconds=time.monotonic() - started - launch_seconds,
            provider_completed=manifest.get('status') == 'complete', status=manifest.get('status', 'local_error'),
            json_valid=strict_json(destination / 'completion.txt'),
            guard_accepted_revisions=len(validation.get('revisions', [])),
            validation_error=validation.get('error'), local_error=error,
            usage=manifest.get('usage'), provider_seconds=manifest.get('seconds'),
            finish_reason=manifest.get('finish_reason'), only_thinking_changed=new_payload is not None,
            files_sha256={p.name: digest(p) for p in destination.iterdir() if p.is_file()}
                if destination.exists() else {})
        records.append(record)
        summarize(output, records, time.monotonic() - started)
        print(json.dumps({key: record[key] for key in ['index', 'case', 'status',
            'json_valid', 'guard_accepted_revisions', 'elapsed_seconds']}), flush=True)
    report = summarize(output, records, time.monotonic() - started, finished=True)
    write(output / 'seal.json', dict(files_sha256={str(p.relative_to(output)): digest(p)
        for p in sorted(output.rglob('*')) if p.is_file()}))
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('stage', choices=['prepare', 'run'])
    parser.add_argument('--campaign', type=Path, action='append')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = prepare(args.campaign, args.output) if args.stage == 'prepare' else run(args.output)
    print(json.dumps({k: v for k, v in result.items() if k != 'records'}), flush=True)
