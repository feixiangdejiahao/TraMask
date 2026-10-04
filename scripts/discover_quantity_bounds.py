"""Freeze and discover the same quantity-bound contract family for every source trial.

Preparation is local. Run uses the authorized existing provider, one request per
eligible trial, and never retries an interrupted dispatch. Relations remain
hypotheses for a separate constructor and independent complete-test review.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import fcntl
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from relation_search import quantity_bound as relation
from relation_search import quantity_bound_discovery as discovery
from relation_search.checkpoint import digest, read
from relational_gap.provider import dispatch
from scripts.run_contract_selection import frozen, write
from scripts.run_test_admission import _preload_local_imports, _loaded_sources, verify_seal

VERSION = 'uniform-quantity-bound-discovery.v1'


def now():
    return datetime.now(timezone.utc)


def verify(receipt):
    if digest(receipt['path']) != receipt['sha256']:
        raise ValueError('frozen_artifact_changed: '+receipt['path'])


def _deadline(value):
    result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if result.tzinfo is None:
        raise ValueError('deadline_requires_timezone')
    return result.astimezone(timezone.utc)


def _reservation(request):
    return len(request['system'].encode())+len(request['prompt'].encode())+request['max_tokens']+1024


def prepare(args):
    for name, maximum in [('max_calls', 17), ('max_total_tokens', 500000),
                          ('max_prompt_bytes', 96000), ('relations_per_trial', 4)]:
        value = getattr(args, name)
        if type(value) is not int or not 1 <= value <= maximum:
            raise ValueError('invalid_'+name)
    deadline = _deadline(args.deadline_utc)
    verify(read(args.source_cohort/'seal.json'))
    previous = read(args.source_cohort/'prepared.json')
    sources = {}
    for row in previous.get('items', previous.get('cases', [])):
        if not isinstance(row, dict) or not isinstance(row.get('case'), str) or not row.get('source'):
            raise ValueError('source_cohort_requires_original_source_paths')
        case = row['case']
        if Path(case).name != case or case in {'.', '..'}:
            raise ValueError('invalid_trial_artifact_name')
        old = sources.setdefault(case, row['source'])
        if old != row['source']:
            raise ValueError('one_original_source_snapshot_per_trial_required')
    if not sources:
        raise ValueError('empty_source_cohort')
    _preload_local_imports(discovery)
    algorithm = _loaded_sources()
    args.output.mkdir(parents=True, exist_ok=False)
    cases = []
    for case, path in sorted(sources.items()):
        source = Path(path)
        inputs = {name: frozen(source/name) for name in ('corpus.json', 'frontend.json', 'issue.md')}
        result = discovery.prepare(read(source/'corpus.json'), (source/'issue.md').read_text(),
            frontend=read(source/'frontend.json'),
            relation_limit=args.relations_per_trial, max_prompt_bytes=args.max_prompt_bytes)
        directory = args.output/'cases'/case
        local, request = result.pop('catalog'), result.pop('request')
        write(directory/'catalog.json', local)
        write(directory/'analysis.json', result)
        request_ref = None
        if request is not None:
            write(directory/'request.json', request)
            request_ref = frozen(directory/'request.json')
        for receipt in inputs.values():
            verify(receipt)
        cases.append(dict(case=case, source=str(source.resolve()), source_inputs=inputs,
            catalog=frozen(directory/'catalog.json'), analysis=frozen(directory/'analysis.json'),
            request=request_ref, status=result['status'], presented=len(result['presented']),
            omitted=len(result['omitted']), pairs=len(local['pairs'])))
        print(json.dumps(dict(case=case, status=result['status'], pairs=len(local['pairs']),
                              presented=len(result['presented']), omitted=len(result['omitted']))), flush=True)
    verify_seal(algorithm)
    if set(_loaded_sources())-set(algorithm):
        raise ValueError('unsealed_local_import')
    policy = dict(max_calls=args.max_calls, max_total_tokens=args.max_total_tokens,
        max_prompt_bytes=args.max_prompt_bytes, relations_per_trial=args.relations_per_trial,
        deadline_utc=deadline.isoformat(), thinking='enabled', reasoning_effort='high',
        output_tokens=16384, minimum_dispatch_seconds=300,
        trial_order='sorted_trial_names',
        pair_order='source_function_paths_and_declaration_offsets',
        prompt_overflow='omit_whole_pair_with_all_its_evidence; never_truncate_source_evidence',
        interrupted_dispatch='unknown_and_conservative_reservation_no_retry')
    protocol = dict(version=VERSION, cases=cases, denominator=len(cases), policy=policy,
        algorithm=algorithm, source_cohort=frozen(args.source_cohort/'prepared.json'),
        source_cohort_use='Trial names and original source paths only; no candidates or outcomes.',
        provider_calls=0, native_executions=0, evaluation_labels_used=False,
        implementation_bodies_sent=False, relations_are_hypotheses=True, created_utc=now().isoformat())
    write(args.output/'prepared.json', protocol)
    write(args.output/'seal.json', frozen(args.output/'prepared.json'))
    return dict(denominator=len(cases), requests=sum(bool(row['request']) for row in cases),
                pairs=sum(row['pairs'] for row in cases), provider_calls=0)


def _artifacts(directory):
    return {str(path.relative_to(directory)): digest(path) for path in sorted(directory.rglob('*'))
            if path.is_file() and path != directory/'result.json'}


def _cost(receipt, reservation):
    calls = receipt.get('external_model_calls', 0)
    if type(calls) is not int or not 0 <= calls <= 1:
        raise ValueError('invalid_provider_call_receipt')
    uncertain = receipt.get('status') in {'prepared', 'dispatching'}
    usage = receipt.get('usage') or {}
    measured = usage.get('total_tokens')
    if measured is None:
        prompt, completion = usage.get('prompt_tokens'), usage.get('completion_tokens')
        if all(type(n) is int and n >= 0 for n in (prompt, completion)):
            measured = prompt+completion
    known = type(measured) is int and measured >= 0 and not uncertain
    return dict(provider_calls=calls, reserved_calls=int(uncertain and not calls),
        measured_tokens=measured if known and calls else 0,
        reserved_tokens=reservation if (calls or uncertain) and not known else 0,
        usage_missing=int(bool(calls or uncertain) and not known))


def _totals(rows):
    keys = ('provider_calls', 'reserved_calls', 'measured_tokens', 'reserved_tokens', 'usage_missing')
    result = {key: sum(row[key] for row in rows) for key in keys}
    return dict(result, accounted_calls=result['provider_calls']+result['reserved_calls'],
                accounted_tokens=result['measured_tokens']+result['reserved_tokens'])


def _unknown(reason):
    return dict(status='unknown', relations=[], errors=[dict(reason=reason)],
                semantic_status='hypothesis_pending_independent_audit')


def run(args):
    root = args.input
    with (root/'.run.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        verify(read(root/'seal.json'))
        protocol = read(root/'prepared.json')
        if protocol['version'] != VERSION:
            raise ValueError('unsupported_discovery_protocol')
        verify_seal(protocol['algorithm']); verify(protocol['source_cohort'])
        policy = protocol['policy']; deadline = _deadline(policy['deadline_utc'])
        rows = []
        for entry in protocol['cases']:
            directory = root/'cases'/entry['case']
            for receipt in [entry['catalog'], entry['analysis'], *entry['source_inputs'].values()]:
                verify(receipt)
            if entry['request']:
                verify(entry['request'])
            if (directory/'result.json').exists():
                row = read(directory/'result.json')
                if row['case'] != entry['case'] or row['artifacts'] != _artifacts(directory):
                    raise ValueError('completed_discovery_artifacts_changed')
                verify(row['relations']); rows.append(row)
                continue
            cost = dict(provider_calls=0, reserved_calls=0, measured_tokens=0,
                        reserved_tokens=0, usage_missing=0)
            decision = _unknown(entry['status'])
            if entry['request']:
                request = read(entry['request']['path'])
                if request['id'] != discovery.request_identity(request):
                    raise ValueError('dispatch_identity_changed')
                reservation = _reservation(request)
                claim = directory/'dispatch_claim.json'
                completion = directory/'completion'; manifest = completion/'manifest.json'
                if manifest.exists() and not claim.exists():
                    raise ValueError('provider_receipt_without_dispatch_claim')
                if claim.exists():
                    recorded = read(claim)
                    if recorded['request'] != entry['request'] or recorded['reserved_tokens'] != reservation:
                        raise ValueError('dispatch_claim_changed')
                    # A surviving claim proves this request was offered already.
                    # Its missing receipt never authorizes a duplicate request.
                    decision = _unknown('interrupted_dispatch_without_complete_receipt')
                    cost.update(reserved_calls=1, reserved_tokens=reservation, usage_missing=1)
                else:
                    totals = _totals(rows)
                    if (totals['accounted_calls'] >= policy['max_calls']
                            or totals['accounted_tokens']+reservation > policy['max_total_tokens']):
                        decision = _unknown('model_budget')
                    elif (deadline-now()).total_seconds() < policy['minimum_dispatch_seconds']:
                        decision = _unknown('deadline')
                    else:
                        write(claim, dict(request=entry['request'], reserved_tokens=reservation,
                                          reserved_calls=1, created_utc=now().isoformat()))
                        try:
                            dispatch(request, completion, root=ROOT)
                        except Exception as exc:
                            # Provider/configuration errors must not expose URLs
                            # or secrets through exception strings.
                            decision = _unknown('dispatch_exception_'+type(exc).__name__)
                            cost.update(reserved_calls=1, reserved_tokens=reservation, usage_missing=1)
                if manifest.exists():
                    receipt = read(manifest)
                    if receipt.get('request_id') != request['id']:
                        raise ValueError('provider_receipt_request_mismatch')
                    wire = completion/'request.json'
                    if not wire.exists() or digest(wire) != receipt.get('request_sha256'):
                        raise ValueError('provider_wire_receipt_mismatch')
                    cost = _cost(receipt, reservation)
                    decision = _unknown('provider_'+receipt['status'])
                    if receipt['status'] == 'complete':
                        decision = discovery.decide(read(entry['catalog']['path']), request,
                            (completion/'completion.txt').read_text(),
                            read(entry['source_inputs']['corpus.json']['path']),
                            Path(entry['source_inputs']['issue.md']['path']).read_text(),
                            frontend=read(entry['source_inputs']['frontend.json']['path']),
                            finish_reason=receipt.get('finish_reason'))
            write(directory/'decision.json', decision)
            target = root/'relations'/(entry['case']+'.json')
            write(target, dict(version=relation.IR_VERSION, relations=decision['relations']))
            row = dict(case=entry['case'], status=decision['status'], selected=len(decision['relations']),
                       relations=frozen(target), artifacts=_artifacts(directory), **cost)
            write(directory/'result.json', row); rows.append(row)
            print(json.dumps(dict(case=entry['case'], status=row['status'], selected=row['selected'],
                                  **_totals(rows))), flush=True)
        verify_seal(protocol['algorithm'])
        summary = dict(version=VERSION, denominator=protocol['denominator'], results=rows,
            result_receipts=[frozen(root/'cases'/row['case']/'result.json') for row in rows],
            selected_relations=sum(row['selected'] for row in rows), native_executions=0,
            independent_semantic_audit_complete=False, relations_are_hypotheses=True,
            prepared=frozen(root/'prepared.json'), **_totals(rows))
        write(root/'summary.json', summary)
        return {key: value for key, value in summary.items() if key not in {'results', 'result_receipts'}}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('stage', choices=['prepare', 'run'])
    parser.add_argument('--source-cohort', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--input', type=Path)
    parser.add_argument('--max-calls', type=int, default=17)
    parser.add_argument('--max-total-tokens', type=int, default=500000)
    parser.add_argument('--max-prompt-bytes', type=int, default=96000)
    parser.add_argument('--relations-per-trial', type=int, default=4)
    parser.add_argument('--deadline-utc', default='2026-10-05T01:19:39Z')
    args = parser.parse_args()
    if args.stage == 'prepare' and (args.source_cohort is None or args.output is None):
        parser.error('prepare requires --source-cohort and --output')
    if args.stage == 'run' and args.input is None:
        parser.error('run requires --input')
    print(json.dumps(prepare(args) if args.stage == 'prepare' else run(args)))
