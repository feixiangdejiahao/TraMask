"""Fixed atomic generation slots over sealed R18 anchor contexts.

Reuse R18 raw-response decoding, semantic enrichment/review and controlled
native execution through private globals. Never change its module globals.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import fcntl
import json
from pathlib import Path
import sys
from types import FunctionType

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from relation_search import atomic_contract_gap_proposals as relation
from relation_search.checkpoint import read
from relational_gap.provider import dispatch
from scripts import run_contract_gap_generation_search as harness
from scripts import run_test_admission as admission
from scripts.run_contract_repair_search import frozen, verify, write
from scripts.discover_quantity_bounds import _artifacts, _cost, _reservation, _totals

VERSION = 'controlled-atomic-contract-gap-generation.v1'
EXPECTED_TRIALS = 17
one_run = harness.one_run


def _engine():
    namespace = dict(vars(harness))
    overrides = dict(__name__=__name__, __file__=__file__, VERSION=VERSION,
        relation=relation, dispatch=dispatch, one_run=one_run,
        _verify_protocol=_verify_protocol, _verify_case_inputs=_verify_case_inputs,
        _generation_case_result=_generation_case_result)
    namespace.update(overrides)
    for name, function in vars(harness).items():
        if name not in overrides and isinstance(function, FunctionType) and function.__module__ == harness.__name__:
            bound = FunctionType(function.__code__, namespace, name, function.__defaults__, function.__closure__)
            bound.__kwdefaults__ = function.__kwdefaults__
            namespace[name] = bound
    return namespace


def _verify_protocol(protocol, phase='semantic_native'):
    if protocol.get('version') != VERSION or protocol.get('phase') != phase or protocol.get('policy') != relation.POLICY:
        raise ValueError('Unsupported atomic protocol')
    compatible = dict(protocol, version=harness.VERSION)
    harness._verify_protocol(compatible, phase)
    if protocol['trial_denominator'] != EXPECTED_TRIALS:
        raise ValueError('Complete seventeen-trial cohort required')
    if protocol['generation_policy'] != GENERATION_POLICY or protocol['semantic_policy'] != SEMANTIC_POLICY:
        raise ValueError('Atomic fixed budget differs')
    verify(protocol['source_cohort'])
    if protocol['reused_harness'] != frozen(harness.__file__) or protocol['reused_decoder'] != frozen(relation.core.__file__):
        raise ValueError('Inherited R18 code differs')
    for case in protocol['cases']:
        if [slot['slot'] for slot in case['slots']] != [1, 2, 3]:
            raise ValueError('Incomplete fixed atomic slot ledger')


GENERATION_POLICY = dict(max_calls=45, max_total_tokens=1000000, max_calls_per_trial=3,
    max_prompt_bytes=96000, max_output_tokens=16384, thinking='enabled', reasoning_effort='high',
    ordering='slot1_all_sorted_trials_then_slot2_then_slot3', no_retry=True, refill=False)
SEMANTIC_POLICY = dict(max_calls=45, max_total_tokens=1500000, max_prompt_bytes=96000,
    max_output_tokens=16384, thinking='enabled', reasoning_effort='high',
    ordering='original slot ranks round robin over sorted trial names',
    unknown='not executed; not an invalid-test judgment', native_outcomes_sent=False,
    generation_basis_sent=False)


def _verify_case_inputs(case):
    harness._verify_case_inputs(case)
    for receipt in (case['inherited_generation_preparation'], case.get('inherited_generation_request')):
        if receipt: verify(receipt)
    inherited = read(case['inherited_generation_preparation']['path'])
    for slot in case['slots']:
        verify(slot['preparation'])
        expected = relation.prepare_slot(inherited, slot['slot'])
        if read(slot['preparation']['path']) != expected:
            raise ValueError('Atomic preparation differs from sealed inherited context')
        if (slot['status'] != expected['status']
                or slot['seed_alias'] != expected.get('inherited_seed_alias')):
            raise ValueError('Atomic anchor or preparation status differs')
        if slot['request']:
            verify(slot['request'])
            if read(slot['request']['path']) != expected['request']:
                raise ValueError('Atomic slot request differs')
        elif expected['request'] is not None:
            raise ValueError('Atomic request omitted')


def prepare(args):
    source_root = args.source_cohort.resolve()
    if read(source_root/'seal.json') != frozen(source_root/'prepared.json'):
        raise ValueError('R18 source preparation seal differs')
    previous = read(source_root/'prepared.json')
    harness._verify_protocol(previous, 'generation')
    # R22 necessarily loads new modules absent from R18's process closure.
    # Verify the inherited bytes, then seal the actually executed R22 closure.
    harness._verify_nested_receipts(previous['algorithm'])
    harness._verify_nested_receipts(previous['algorithm_entrypoints'])
    if (previous['algorithm_entrypoints']['driver'] != frozen(harness.__file__)
            or previous['algorithm_entrypoints']['constructor'] != frozen(relation.core.__file__)):
        raise ValueError('R18 inherited decoder or driver differs')
    if len(previous['cases']) != EXPECTED_TRIALS:
        raise ValueError('Complete seventeen-trial R18 source preparation required')
    deadline = admission._deadline(args.deadline_utc)
    if deadline is None:
        raise ValueError('Deadline required')
    args.output.mkdir(parents=True, exist_ok=False)
    cases = []
    for old in previous['cases']:
        harness._verify_case_inputs(old)
        prepared = read(old['generation']['path'])
        if old['generation_request'] and read(old['generation_request']['path']) != prepared['request']:
            raise ValueError('Inherited source request differs from preparation')
        slots = []
        directory = args.output/'cases'/old['case']/'generation'
        for rank in (1, 2, 3):
            result = relation.prepare_slot(prepared, rank)
            target = directory/f'slot_{rank:04d}'
            write(target/'preparation.json', result)
            if result['request'] is not None: write(target/'request.json', result['request'])
            slots.append(dict(slot=rank, preparation=frozen(target/'preparation.json'),
                request=frozen(target/'request.json') if result['request'] is not None else None,
                status=result['status'], seed_alias=result.get('inherited_seed_alias')))
        write(directory/'preparation.json', dict(version=relation.VERSION, policy=relation.POLICY,
            inherited_preparation=old['generation'], inherited_request=old['generation_request'], slots=slots))
        cases.append(dict(old, generation=frozen(directory/'preparation.json'), generation_request=None,
            inherited_generation_preparation=old['generation'],
            inherited_generation_request=old['generation_request'], slots=slots,
            candidates=[], status='atomic_slots_prepared'))
    admission._preload_local_imports(sys.modules[__name__])
    engine = _engine()
    protocol = dict(previous, version=VERSION, phase='generation', policy=relation.POLICY,
        algorithm=admission._loaded_sources(), algorithm_entrypoints=engine['_entrypoints'](),
        cases=cases, source_cohort=frozen(source_root/'prepared.json'),
        source_cohort_use='Only sealed R18 preparation, original source inputs and complete prepared anchor contexts. Never R18 generation results or outcomes.',
        reused_harness=frozen(harness.__file__), reused_decoder=frozen(relation.core.__file__),
        deadline_utc=deadline.isoformat(), generation_policy=GENERATION_POLICY,
        semantic_policy=SEMANTIC_POLICY, max_native_executions=4*len(cases),
        comparative_limits=[*previous['comparative_limits'],
            'Joint task-grain/context experiment, not a pure cost ablation: separate calls alter independent reasoning budget and overhead.',
            'At most three DISTINCT already-prepared R18 anchors; never retrieve omitted anchors or repeat an anchor.',
            'All three slots per trial remain in the ledger. Empty/unknown/refused/duplicate/budget-withheld slots are not refilled.',
            'Fresh review retains the same R18 candidate-specific original-source enrichment and complete-test transport.',
            'The 1M generation cap does not guarantee all45 requests; actual and reserved usage govern stopping.'],
        created_utc=datetime.now(timezone.utc).isoformat())
    _verify_protocol(protocol, 'generation'); engine['_verify_algorithm'](protocol)
    write(args.output/'prepared.json', protocol); write(args.output/'seal.json', frozen(args.output/'prepared.json'))
    return dict(trials=len(cases), slots=3*len(cases), requests=sum(bool(s['request']) for c in cases for s in c['slots']),
        prepared=frozen(args.output/'prepared.json'), provider_calls=0, native_executions=0)


def _slot_case(case, slot):
    return dict(case, generation=slot['preparation'], generation_request=slot['request'])


def _slot_path(root, case, slot):
    return root/'cases'/case['case']/'generation'/f"slot_{slot['slot']:04d}"


def _slot_result(root, case, slot):
    directory = _slot_path(root, case, slot); row = read(directory/'result.json')
    if (row['case'] != case['case'] or row['slot'] != slot['slot']
            or row['preparation'] != slot['preparation'] or row['artifacts'] != _artifacts(directory)
            or row['decoded'] != frozen(directory/'decoded.json')):
        raise ValueError('Completed atomic slot artifacts changed')
    decoded, cost = _engine()['_generation_evidence'](_slot_case(case, slot), directory)
    if read(row['decoded']['path']) != decoded or any(row[key] != value for key,value in cost.items()):
        raise ValueError('Atomic slot decoding or accounting differs from raw evidence')
    if (row['status'] != decoded['status'] or row['candidates'] != len(decoded['candidates'])
            or row['refusals'] != len(decoded['rejected'])):
        raise ValueError('Atomic slot inventory differs')
    manifest = directory/'completion/manifest.json'
    finish = read(manifest).get('finish_reason') if manifest.exists() else None
    if row['provider_finish_reason'] != finish:
        raise ValueError('Atomic finish reason differs from raw receipt')
    return row


def _aggregate_case(root, case):
    rows = [_slot_result(root, case, slot) for slot in case['slots']]
    records = [dict(slot=slot['slot'], decoded=read(row['decoded']['path']), decoded_receipt=row['decoded'],
        preparation_status=slot['status'], dispatch_withheld_reason=row.get('dispatch_withheld_reason'),
        provider_finish_reason=row['provider_finish_reason'])
        for slot,row in zip(case['slots'], rows)]
    return relation.aggregate(records), rows


def _generation_case_result(root, case):
    directory = root/'cases'/case['case']/'generation'
    row = read(directory/'result.json'); decoded, slots = _aggregate_case(root, case)
    if (row['case'] != case['case'] or row['preparation'] != case['generation']
            or row['artifacts'] != _artifacts(directory)
            or row['decoded'] != frozen(directory/'decoded.json') or read(row['decoded']['path']) != decoded
            or row['slot_results'] != [frozen(_slot_path(root,case,s)/'result.json') for s in case['slots']]
            or row['status'] != decoded['status'] or row['candidates'] != len(decoded['candidates'])
            or row['refusals'] != len(decoded['rejected'])
            or any(row[key] != value for key,value in _totals(slots).items())):
        raise ValueError('Aggregate atomic ledger differs from complete raw slot evidence')
    return row


def generate(args):
    root = args.input
    with (root/'.generation.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        protocol = read(root/'prepared.json'); engine = _engine()
        if read(root/'seal.json') != frozen(root/'prepared.json'):
            raise ValueError('Atomic generation seal differs')
        _verify_protocol(protocol, 'generation'); engine['_verify_algorithm'](protocol)
        if (root/'generation_summary.json').exists():
            return engine['_expand'](root, protocol, engine['_verified_generation'](root,protocol))
        completed = []; policy = protocol['generation_policy']
        deadline = admission._deadline(protocol['deadline_utc'])
        for rank in (1, 2, 3):
            for case in protocol['cases']:
                slot = case['slots'][rank-1]; directory = _slot_path(root,case,slot)
                _verify_case_inputs(case)
                if (directory/'result.json').exists():
                    completed.append(_slot_result(root,case,slot)); continue
                reason = None
                if slot['request']:
                    request = read(slot['request']['path']); claim = directory/'dispatch_claim.json'
                    if not claim.exists():
                        if (directory/'completion/manifest.json').exists():
                            raise ValueError('Provider receipt without atomic dispatch claim')
                        totals = _totals(completed); reservation = _reservation(request)
                        if totals['accounted_calls'] >= policy['max_calls'] or totals['accounted_tokens']+reservation > policy['max_total_tokens']:
                            reason = 'generation_budget'
                        elif (deadline-datetime.now(timezone.utc)).total_seconds() < 300:
                            reason = 'deadline'
                        else:
                            write(claim, dict(request=slot['request'], reserved_tokens=reservation,
                                reserved_calls=1, created_utc=datetime.now(timezone.utc).isoformat()))
                            try: dispatch(request,directory/'completion',root=ROOT)
                            except Exception as exc:
                                write(directory/'dispatch_exception.json',dict(exception_type=type(exc).__name__))
                decoded, cost = engine['_generation_evidence'](_slot_case(case,slot),directory)
                write(directory/'decoded.json',decoded)
                manifest = directory/'completion/manifest.json'
                row = dict(case=case['case'],slot=rank,preparation=slot['preparation'],
                    decoded=frozen(directory/'decoded.json'),status=decoded['status'],
                    candidates=len(decoded['candidates']),refusals=len(decoded['rejected']),
                    provider_finish_reason=read(manifest).get('finish_reason') if manifest.exists() else None,
                    dispatch_withheld_reason=reason,artifacts=_artifacts(directory),**cost)
                write(directory/'result.json',row);completed.append(row)
                print(json.dumps(dict(case=case['case'],slot=rank,status=row['status'],**_totals(completed))),flush=True)
        rows = []
        for case in protocol['cases']:
            directory = root/'cases'/case['case']/'generation'; decoded, slots = _aggregate_case(root,case)
            write(directory/'decoded.json',decoded)
            row = dict(case=case['case'],preparation=case['generation'],decoded=frozen(directory/'decoded.json'),
                status=decoded['status'],candidates=len(decoded['candidates']),refusals=len(decoded['rejected']),
                slot_results=[frozen(_slot_path(root,case,s)/'result.json') for s in case['slots']],
                artifacts=_artifacts(directory),**_totals(slots))
            write(directory/'result.json',row);rows.append(row)
        engine['_verify_algorithm'](protocol)
        summary = dict(version=VERSION,stage='complete',prepared=frozen(root/'prepared.json'),
            trial_denominator=protocol['trial_denominator'],results=rows,
            result_receipts=[frozen(root/'cases'/row['case']/'generation/result.json') for row in rows],
            native_executions=0,**_totals(rows))
        write(root/'generation_summary.json',summary)
        write(root/'generation_summary_seal.json',frozen(root/'generation_summary.json'))
        return engine['_expand'](root,protocol,engine['_verified_generation'](root,protocol))


def review_all(args): return _engine()['review_all'](args)
def run(args): return _engine()['run'](args)


if __name__ == '__main__':
    parser=argparse.ArgumentParser(__doc__)
    parser.add_argument('stage',choices=['prepare','generate','review','run'])
    parser.add_argument('--source-cohort',type=Path);parser.add_argument('--output',type=Path)
    parser.add_argument('--input',type=Path);parser.add_argument('--deadline-utc')
    args=parser.parse_args()
    if args.stage=='prepare':
        if args.source_cohort is None or args.output is None or not args.deadline_utc:
            parser.error('prepare requires --source-cohort, --output and --deadline-utc')
        result=prepare(args)
    else:
        if args.input is None: parser.error('--input is required')
        if args.stage in {'review','run'} and read(args.input/'prepared.json').get('phase')=='generation':
            args.input=args.input/'native'
        result=generate(args) if args.stage=='generate' else review_all(args) if args.stage=='review' else run(args)
    print(json.dumps(result))
