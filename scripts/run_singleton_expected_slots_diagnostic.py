"""Bounded paired dispatch of an already frozen singleton expected-slot inventory.

This runner never selects candidates, changes prompts, retries, or executes tests.
All original parents, including unsupported and oversized ones, stay in the report.
"""
from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from experimental.singleton_oracle_slots import adapt_response
from relation_search.checkpoint import digest, read, write
from relational_gap.provider import dispatch


def checked(path, checksum):
    if digest(path) != checksum:
        raise ValueError('Frozen artifact changed: ' + str(path))
    return read(path)


def wire_payload(request):
    payload = dict(model='deepseek-v4-flash', temperature=0, max_tokens=16384,
        messages=[dict(role='system', content=request['system']),
                  dict(role='user', content=request['prompt'])],
        response_format={'type': 'json_object'}, stream=False,
        thinking={'type': request.get('thinking', 'disabled')})
    if 'reasoning_effort' in request:
        payload['reasoning_effort'] = request['reasoning_effort']
    return payload


def prepare(directory):
    if (directory/'execution_protocol.json').exists():
        raise ValueError('Execution protocol already exists')
    protocol = checked(directory/'protocol.json', read(directory/'protocol.seal.json')['sha256'])
    summary = checked(directory/'summary.json', read(directory/'summary.seal.json')['sha256'])
    baseline = checked(protocol['inputs']['baseline_protocol'], protocol['inputs']['baseline_protocol_sha256'])
    if len(summary['records']) != 32 or len(baseline['requests']) != 32:
        raise ValueError('Expected exactly the frozen 32 parent requests')
    for relative, checksum in protocol['code_sha256'].items():
        checked_code = ROOT/relative
        if digest(checked_code) != checksum:
            raise ValueError('Prompt preparation code changed')
    rows = []
    for row, original in zip(summary['records'], baseline['requests']):
        if row['index'] != original['index'] or row['baseline_request_sha256'] != original['request_sha256']:
            raise ValueError('Parent inventory identity changed')
        old = checked(row['baseline_request'], row['baseline_request_sha256'])
        source = Path(old['source_prepared'])
        for name, checksum in row['source_hashes'].items():
            if digest(source/name) != checksum:
                raise ValueError('Source input changed')
        scope = original['scope']
        if not all(scope['matches_authorized_registry'].values()):
            raise ValueError('Parent authorization is incomplete')
        if digest(scope['case_path']) != scope['case_sha256']:
            raise ValueError('Authorized case identity changed')
        record = dict(row, source_prepared=str(source), authorization_scope=scope,
                      baseline_completion=str(Path(protocol['inputs']['baseline_protocol']).parent/'completions'/f"request_{row['index']:03d}"))
        if 'request' in row:
            request = checked(row['request'], row['request_sha256'])
            before, after = wire_payload(old), wire_payload(request)
            if {k:v for k,v in before.items() if k!='messages'} != {k:v for k,v in after.items() if k!='messages'}:
                raise ValueError('Provider parameters changed')
            expected_path = directory/'expected_wire_payloads'/Path(row['request']).name
            write(expected_path, after)
            record.update(expected_wire_payload=str(expected_path.resolve()),
                          expected_wire_payload_sha256=digest(expected_path))
        rows.append(record)
    code = dict(protocol['code_sha256'])
    for relative in ['relational_gap/provider.py', 'relation_search/checkpoint.py',
                     'scripts/run_singleton_expected_slots_diagnostic.py']:
        target = directory/'algorithm_snapshot'/relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT/relative, target)
        code[relative] = digest(ROOT/relative)
    result = dict(created_utc=datetime.now(timezone.utc).isoformat(),
        preparation_protocol_sha256=digest(directory/'protocol.json'),
        preparation_summary_sha256=digest(directory/'summary.json'),
        baseline_protocol_sha256=protocol['inputs']['baseline_protocol_sha256'],
        selection='same 32 fixed parents; all and only previously prepared requests; original order',
        prompt_frozen_before_dispatch=True, outcome_based_selection=False,
        authorization='User authorized all 17 trials and the same configured provider; coordinator authorized this paired 14-request comparison.',
        records=rows, parent_denominator=32, request_limit=sum('request' in row for row in rows),
        max_workers=2, launch_window_seconds=360, request_timeout_seconds=300,
        retries=0, total_provider_concurrency_limit=6,
        model='deepseek-v4-flash', thinking='disabled', temperature=0,
        max_output_tokens_per_request=16384, provider_parameters_changed=False,
        correctness_evaluated=False, code_sha256=code)
    write(directory/'execution_protocol.json', result)
    write(directory/'execution_protocol.seal.json', dict(sha256=digest(directory/'execution_protocol.json')))
    return dict(requests=result['request_limit'], parents=32,
                protocol_sha256=digest(directory/'execution_protocol.json'), external_model_calls=0)


def one(row, directory, started):
    request = checked(row['request'], row['request_sha256'])
    source = Path(row['source_prepared'])
    for name, checksum in row['source_hashes'].items():
        if digest(source/name) != checksum:
            raise ValueError('Frozen source changed before dispatch')
    output = directory/'completions'/Path(row['request']).stem
    launched = time.monotonic()-started
    error = None
    try:
        dispatch(request, output, root=ROOT)
    except Exception as exc:
        error = type(exc).__name__
    manifest = read(output/'manifest.json') if (output/'manifest.json').exists() else {}
    content = (output/'completion.txt').read_text() if (output/'completion.txt').exists() else None
    valid_json, parsed = False, None
    if content is not None:
        try:
            parsed = json.loads(content)
            valid_json = True
            write(output/'parsed_response.json', parsed)
        except (ValueError, UnicodeError):
            pass
    validation = adapt_response(request, parsed, read(source/'corpus.json')) if valid_json else dict(
        status='unknown', reason='no_strict_json_response', revisions=[], oracle_validity='unconfirmed')
    write(output/'validation.json', validation)
    wire_matches = (output/'request.json').exists() and read(output/'request.json') == checked(
        row['expected_wire_payload'], row['expected_wire_payload_sha256'])
    return dict(index=row['index'], case=row['case'], request=row['request'],
        completion=str(output.resolve()), status=manifest.get('status','local_error'),
        launched=True, launch_seconds=launched, elapsed_seconds=time.monotonic()-started-launched,
        provider_completed=manifest.get('status')=='complete', strict_json_valid=valid_json,
        content_chars=len(content) if content is not None else None,
        finish_reason=manifest.get('finish_reason'), usage=manifest.get('usage'),
        external_model_calls=manifest.get('external_model_calls',0),
        adapter_status=validation['status'], adapter_reason=validation.get('reason'),
        accepted_revisions=len(validation['revisions']), oracle_validity='unconfirmed',
        expected_wire_payload_matches=wire_matches, local_error=error,
        files_sha256={path.name:digest(path) for path in output.iterdir() if path.is_file()})


def summarize(directory, parents, completed, started, *, finished):
    by_index = {row['index']: row for row in completed}
    rows = [by_index.get(parent['index'], dict(index=parent['index'], case=parent['case'],
        launched=False, status='not_launched_budget' if 'request' in parent else parent['status'],
        oracle_validity='unknown')) for parent in parents]
    result = dict(finished=finished, parent_denominator=len(parents), records=rows,
        launched=len(completed), statuses=dict(Counter(row['status'] for row in rows)),
        adapter_statuses=dict(Counter(row['adapter_status'] for row in completed)),
        strict_json_valid=sum(row['strict_json_valid'] for row in completed),
        accepted_revisions=sum(row['accepted_revisions'] for row in completed),
        external_model_calls=sum(row['external_model_calls'] for row in completed),
        elapsed_seconds=time.monotonic()-started, correctness_evaluated=False,
        interpretation='Syntax acceptance and preserve decisions are unconfirmed; all 32 parents remain in denominator.')
    write(directory/'diagnostic.json', result)
    return result


def run(directory):
    protocol = checked(directory/'execution_protocol.json', read(directory/'execution_protocol.seal.json')['sha256'])
    checked(directory/'protocol.json', protocol['preparation_protocol_sha256'])
    checked(directory/'summary.json', protocol['preparation_summary_sha256'])
    for relative, checksum in protocol['code_sha256'].items():
        if digest(ROOT/relative) != checksum:
            raise ValueError('Frozen diagnostic code changed')
    if (directory/'launch.json').exists():
        raise ValueError('A launched comparison cannot be restarted')
    write(directory/'launch.json', dict(started_utc=datetime.now(timezone.utc).isoformat(),
        execution_protocol_sha256=digest(directory/'execution_protocol.json'), max_workers=protocol['max_workers']))
    started, completed = time.monotonic(), []
    pending_rows = iter(row for row in protocol['records'] if 'request' in row)
    with ThreadPoolExecutor(max_workers=protocol['max_workers']) as executor:
        active = {}
        exhausted = False
        while active or not exhausted:
            while len(active)<protocol['max_workers'] and not exhausted:
                if time.monotonic()-started >= protocol['launch_window_seconds']:
                    exhausted = True
                    break
                row = next(pending_rows, None)
                if row is None:
                    exhausted = True
                    break
                active[executor.submit(one,row,directory,started)] = row
            if not active:
                break
            done, _ = wait(active, timeout=1, return_when=FIRST_COMPLETED)
            for future in done:
                row = future.result()
                del active[future]
                completed.append(row)
                summarize(directory,protocol['records'],completed,started,finished=False)
                print(json.dumps({key:row[key] for key in ['index','case','status','strict_json_valid',
                    'adapter_status','accepted_revisions','elapsed_seconds']}),flush=True)
                if not row['expected_wire_payload_matches']:
                    raise ValueError('Actual payload differed from frozen expected request')
    result = summarize(directory,protocol['records'],completed,started,finished=True)
    write(directory/'diagnostic.seal.json',dict(sha256=digest(directory/'diagnostic.json')))
    return {key:value for key,value in result.items() if key!='records'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('stage', choices=['prepare','run'])
    parser.add_argument('--directory', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps({'prepare':prepare,'run':run}[args.stage](args.directory)),flush=True)
