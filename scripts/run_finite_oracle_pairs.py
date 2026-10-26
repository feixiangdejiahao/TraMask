"""Run each sealed paired oracle question once, with explicit member coverage."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from prototypes.finite_oracle_questions import validate_question
from relational_gap.provider import dispatch, encoded
from scripts.prepare_finite_oracle_pairs import verify_pair, wire_preview

TERMINAL = {'complete', 'error', 'configuration_error'}


def read(path):
    return json.loads(Path(path).read_text())


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True, ensure_ascii=False, indent=2)+'\n')


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def verified_input(directory):
    directory = Path(directory).resolve()
    protocol, ready = read(directory/'protocol.json'), read(directory/'ready.json')
    if ready['protocol_sha256'] != digest(directory/'protocol.json'):
        raise ValueError('Prepared protocol changed')
    if [r['case'] for r in ready['records']] != protocol['cases']:
        raise ValueError('Prepared case denominator changed')
    for name, checksum in read(directory/'seal.json')['files_sha256'].items():
        if digest(directory/name) != checksum:
            raise ValueError('Sealed input changed: '+name)
    for name, checksum in protocol['code_sha256'].items():
        if digest(ROOT/name) != checksum or digest(directory/'code_snapshot'/name) != checksum:
            raise ValueError('Prepared generator changed: '+name)
    for case, files in protocol['input_sha256'].items():
        for name, checksum in files.items():
            if digest(Path(protocol['inventory'])/case/name) != checksum:
                raise ValueError('Original source changed: '+case+'/'+name)
    records = []
    for row in ready['records']:
        if row['status'] != 'offerable':
            continue
        a, b = [read(row['arms'][arm]['request']) for arm in ['template','expanded']]
        _, identity = verify_pair(a, b)
        if identity != row['identity']:
            raise ValueError('Prepared pair identity changed')
        for arm in ['template','expanded']:
            member = row['arms'][arm]
            request, preview = Path(member['request']), Path(member['wire_preview'])
            if request != directory/row['case']/arm/'request.json':
                raise ValueError('Request is outside the fixed pair location')
            if digest(request) != member['request_sha256'] or digest(preview) != member['wire_preview_sha256']:
                raise ValueError('Prepared request or preview changed')
            if preview.read_bytes() != encoded(wire_preview(read(request))):
                raise ValueError('Prepared preview differs from provider encoding')
        records.append(row)
    return protocol, records


def complete(request_path, output):
    request_path, output = Path(request_path), Path(output)
    request = read(request_path)
    if output.exists():
        manifest_path = output/'manifest.json'
        if not manifest_path.exists() or read(manifest_path).get('status') not in TERMINAL:
            raise ValueError('Audit the unfinished attempt before resuming; no automatic retry')
        record = read(manifest_path)
        if record.get('request_id') != request['id']:
            raise ValueError('Existing attempt belongs to another request')
    else:
        record = dispatch(request, output, root=ROOT)
    actual = output/'request.json'
    if actual.exists() and actual.read_bytes() != encoded(wire_preview(request)):
        raise ValueError('Actual provider wire differs from the sealed preview')
    if actual.exists() and digest(actual) != record.get('request_sha256'):
        raise ValueError('Actual provider wire differs from its receipt')
    if record['status'] != 'complete':
        return dict(status=record['status'], error_type=record.get('error_type'),
                    offered_members=len(request['offered']), answered_members=0,
                    revisions=0, all_members_answered=False, usage=record.get('usage'))
    if not actual.exists():
        raise ValueError('Complete response is missing the recorded request')
    validation = output/'validation.json'
    if not validation.exists():
        corpus = read(Path(request['source_prepared'])/'corpus.json')
        try:
            outcome = validate_question(request, (output/'completion.txt').read_text(), corpus)
        except (ValueError, TypeError, KeyError, AttributeError) as error:
            outcome = dict(revisions=[], decisions=[], error=type(error).__name__,
                members=[dict(alias=alias, candidate_id=row['candidate']['id'],
                              status='validation_error', semantic_correctness='unreviewed')
                         for alias,row in request['offered'].items()],
                offered_members=len(request['offered']), answered_members=0,
                all_members_answered=False)
        write(validation, outcome)
    else:
        outcome = read(validation)
    return dict(status=record['status'], offered_members=outcome['offered_members'],
                answered_members=outcome['answered_members'], revisions=len(outcome['revisions']),
                all_members_answered=outcome['all_members_answered'],
                validation_error=outcome.get('error'), usage=record.get('usage'),
                finish_reason=record.get('finish_reason'), seconds=record.get('seconds'))


def run(directory, workers=2):
    directory = Path(directory).resolve()
    if workers not in {1,2,4}:
        raise ValueError('Use one, two or four fixed workers')
    protocol, records = verified_input(directory)
    order = {}
    for row in records:
        arms = ['template','expanded']
        if int(hashlib.sha256(row['case'].encode()).hexdigest(),16)%2:
            arms.reverse()
        order[row['case']] = arms
    execution = dict(version='finite-oracle-pair-dispatch-v1',
        prepared_ready_sha256=digest(directory/'ready.json'),
        prepared_protocol_sha256=digest(directory/'protocol.json'),
        driver_sha256=digest(__file__), workers=workers, retries=0,
        maximum_new_requests=2*len(records), arm_order_by_case=order,
        prior_timebox_score_frozen=True, model_settings=protocol['model_settings'])
    receipt = directory/'execution_protocol.json'
    if receipt.exists() and read(receipt) != execution:
        raise ValueError('Dispatch protocol changed on resume')
    write(receipt, execution)

    def pair(row):
        output = []
        for arm in order[row['case']]:
            folder = directory/row['case']/arm
            result = complete(folder/'request.json', folder/'completion')
            result.update(case=row['case'], arm=arm, members=row['member_ids'],
                          completion=str(folder/'completion'))
            write(folder/'execution_result.json', result)
            output.append(result)
            print(json.dumps({k:result[k] for k in ['case','arm','status','answered_members','offered_members']},sort_keys=True),flush=True)
        return output

    results = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(pair,row) for row in records]
        for future in as_completed(futures):
            results.extend(future.result())
            results.sort(key=lambda row:(row['case'],row['arm']))
            write(directory/'execution_results.json',results)
    summary = dict(cases=len(protocol['cases']), offerable_pairs=len(records),
        requests=len(results), complete=sum(r['status']=='complete' for r in results),
        member_answers=sum(r['answered_members'] for r in results),
        member_opportunities=sum(r['offered_members'] for r in results),
        all_members_answered_questions=sum(r['all_members_answered'] for r in results),
        complete_semantics='unreviewed', subject_executions=0,
        completed_at=datetime.now(timezone.utc).isoformat())
    write(directory/'execution_complete.json',summary)
    return summary


if __name__ == '__main__':
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('--input',required=True,type=Path)
    parser.add_argument('--workers',type=int,default=2)
    args = parser.parse_args()
    print(json.dumps(run(args.input,args.workers),sort_keys=True))
