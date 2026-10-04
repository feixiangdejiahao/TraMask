"""Plan declaration IDs, then freeze a new R18-compatible generation protocol.

The planning stage never generates or executes tests. Shared sealed modules
remain unchanged. Generation/review/native reuse private harness globals.
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
from relation_search import declaration_contract_planning as planning
from relation_search import planned_contract_gap_proposals as relation
from relation_search.checkpoint import read
from relational_gap.provider import dispatch
from scripts import run_contract_gap_generation_search as harness
from scripts import run_test_admission as admission
from scripts.discover_quantity_bounds import _artifacts, _cost, _reservation, _totals
from scripts.run_contract_repair_search import frozen, verify, write

VERSION = 'controlled-planned-contract-gap-generation.v1'
PLANNING_VERSION = 'controlled-declaration-id-context-planning.v1'
PLANNING_POLICY = dict(max_calls=17, max_total_tokens=500000, max_catalog_bytes=64000,
    max_prompt_bytes=96000, max_output_tokens=8192, max_selected_ids=12,
    max_selected_evidence_bytes=24000, thinking='enabled', reasoning_effort='high',
    ordering='sorted_trial_names', interrupted_dispatch='unknown_and_reserved_cost_no_retry',
    fallback='original_R18_catalog_with_planning_status_and_costs')
one_run = harness.one_run


def _engine():
    namespace = dict(vars(harness))
    overrides = dict(__name__=__name__, __file__=__file__, VERSION=VERSION,
        relation=relation, dispatch=dispatch, one_run=one_run,
        _verify_protocol=_verify_protocol, _verify_case_inputs=_verify_case_inputs)
    namespace.update(overrides)
    for name, function in vars(harness).items():
        if name not in overrides and isinstance(function, FunctionType) and function.__module__ == harness.__name__:
            copied = FunctionType(function.__code__, namespace, name, function.__defaults__, function.__closure__)
            copied.__kwdefaults__ = function.__kwdefaults__
            namespace[name] = copied
    return namespace


def _verify_case_inputs(case):
    harness._verify_case_inputs(case)
    for key in ('inherited_generation', 'planning_preparation', 'planning_result', 'planning_decoded'):
        verify(case[key])
    inherited = read(case['inherited_generation']['path'])
    plan = read(case['planning_preparation']['path'])
    selection = read(case['planning_decoded']['path'])
    expected = planning.generation_preparation(inherited, plan, selection)
    actual = case.get('generation_preparation', case['generation'])
    if read(actual['path']) != expected:
        raise ValueError('Generation context differs from exact source plan')


def _verify_protocol(protocol, phase='semantic_native'):
    if protocol.get('version') != VERSION or protocol.get('policy') != relation.POLICY:
        raise ValueError('Unsupported planned generation protocol')
    harness._verify_protocol(dict(protocol, version=harness.VERSION), phase)
    if protocol['trial_denominator'] != 17 or protocol['planning_policy'] != PLANNING_POLICY:
        raise ValueError('Planning cohort or budget changed')
    planning_root = Path(protocol['planning_root'])
    prior, summary = _verified_plan(planning_root)
    if (protocol['planning_protocol'] != frozen(planning_root/'prepared.json')
            or protocol['planning_summary'] != frozen(planning_root/'summary.json')
            or protocol['planning_costs'] != _totals(summary['results'])
            or protocol['source_cohort'] != prior['inherited_prepared']):
        raise ValueError('Planning origin or costs changed')


def _verify_planning_protocol(root):
    if read(root/'seal.json') != frozen(root/'prepared.json'):
        raise ValueError('Planning protocol seal differs')
    protocol = read(root/'prepared.json')
    if (protocol['version'] != PLANNING_VERSION or protocol['policy'] != PLANNING_POLICY
            or protocol['constructor_policy'] != planning.POLICY):
        raise ValueError('Planning protocol differs')
    names = [case['case'] for case in protocol['cases']]
    if names != sorted(set(names)) or len(names) != protocol['trial_denominator'] or len(names) != 17:
        raise ValueError('Complete sorted seventeen-trial planning cohort required')
    admission._preload_local_imports(sys.modules[__name__])
    admission._verify_sources(protocol['algorithm_entrypoints'], protocol['algorithm'])
    verify(protocol['inherited_prepared'])
    for case in protocol['cases']:
        harness._verify_case_inputs(case['inherited_case'])
        verify(case['preparation'])
        prepared = read(case['preparation']['path'])
        if case['request']:
            verify(case['request'])
            if read(case['request']['path']) != prepared['request']:
                raise ValueError('Planning request differs from preparation')
        elif prepared['request'] is not None:
            raise ValueError('Planning request omitted')
    return protocol


def prepare(args):
    source = args.source_cohort.resolve()
    if read(source/'seal.json') != frozen(source/'prepared.json'):
        raise ValueError('Inherited R18 preparation seal differs')
    previous = read(source/'prepared.json')
    harness._verify_protocol(previous, 'generation')
    harness._verify_nested_receipts(previous['algorithm'])
    harness._verify_nested_receipts(previous['algorithm_entrypoints'])
    if (len(previous['cases']) != 17 or previous['algorithm_entrypoints']['driver'] != frozen(harness.__file__)
            or previous['algorithm_entrypoints']['constructor'] != frozen(relation.core.__file__)):
        raise ValueError('Exact R18 source preparation required')
    deadline = admission._deadline(args.deadline_utc)
    if deadline is None:
        raise ValueError('Deadline required')
    args.output.mkdir(parents=True, exist_ok=False)
    cases = []
    for old in previous['cases']:
        harness._verify_case_inputs(old)
        inherited = read(old['generation']['path'])
        corpus, _ = harness._context(old)
        prepared = planning.prepare(corpus, inherited)
        directory = args.output/'cases'/old['case']/'planning'
        write(directory/'preparation.json', prepared)
        if prepared['request'] is not None:
            write(directory/'request.json', prepared['request'])
        case = dict(case=old['case'], inherited_case=old,
            preparation=frozen(directory/'preparation.json'),
            request=frozen(directory/'request.json') if prepared['request'] else None,
            status=prepared['status'], presented=len(prepared['presented']), omitted=len(prepared['omitted']),
            anchor_count=prepared.get('anchor_count', 0), all_catalog_bytes=prepared.get('all_catalog_bytes', 0),
            catalog_bytes=prepared.get('catalog_bytes', 0), prompt_bytes=prepared['request']['prompt_bytes'] if prepared['request'] else 0)
        cases.append(case)
        print(json.dumps({key: value for key, value in case.items() if key != 'inherited_case'}), flush=True)
    admission._preload_local_imports(sys.modules[__name__])
    protocol = dict(version=PLANNING_VERSION, policy=PLANNING_POLICY, constructor_policy=planning.POLICY,
        algorithm=admission._loaded_sources(), algorithm_entrypoints={
            'driver': frozen(__file__), 'planner': frozen(planning.__file__), 'provider_adapter': frozen(sys.modules[dispatch.__module__].__file__)},
        cases=cases, trial_denominator=17, inherited_prepared=frozen(source/'prepared.json'),
        source_use='Only sealed R18 source preparations, source projections and complete original test text. No R18/R22 generation outputs or evaluations.',
        deadline_utc=deadline.isoformat(), provider_calls=0, native_executions=0,
        created_utc=datetime.now(timezone.utc).isoformat())
    write(args.output/'prepared.json', protocol)
    write(args.output/'seal.json', frozen(args.output/'prepared.json'))
    _verify_planning_protocol(args.output)
    return dict(prepared=frozen(args.output/'prepared.json'), trials=17,
        requests=sum(bool(c['request']) for c in cases), anchors=sum(c['anchor_count'] for c in cases),
        provider_calls=0, native_executions=0)


def _plan_evidence(case, directory):
    prepared = read(case['preparation']['path'])
    zero = dict(provider_calls=0, reserved_calls=0, measured_tokens=0, reserved_tokens=0, usage_missing=0)
    if not case['request']:
        return planning.unknown('planning_input_unavailable'), zero
    request = read(case['request']['path'])
    if request != prepared['request'] or request['id'] != admission._request_identity(request):
        raise ValueError('Planning request identity changed')
    claim = directory/'dispatch_claim.json'
    manifest = directory/'completion/manifest.json'
    if not claim.exists():
        if manifest.exists():
            raise ValueError('Planning receipt without dispatch claim')
        return planning.unknown('not_dispatched'), zero
    reservation = _reservation(request)
    recorded = read(claim)
    if (recorded['request'] != case['request'] or recorded['reserved_calls'] != 1
            or recorded['reserved_tokens'] != reservation):
        raise ValueError('Planning dispatch reservation changed')
    if not manifest.exists():
        return planning.unknown('interrupted_or_failed_dispatch'), dict(zero,
            reserved_calls=1, reserved_tokens=reservation, usage_missing=1)
    receipt = read(manifest)
    if (receipt.get('request_id') != request['id']
            or receipt.get('request_sha256') != admission.digest(directory/'completion/request.json')):
        raise ValueError('Planning provider request receipt changed')
    cost = _cost(receipt, reservation)
    if receipt['status'] != 'complete':
        return planning.unknown('provider_'+receipt['status']), cost
    content = harness.verified_completion(request, directory/'completion', receipt)
    return planning.decode(prepared, content, finish_reason=receipt.get('finish_reason')), cost


def _plan_result(root, case):
    directory = root/'cases'/case['case']/'planning'
    row = read(directory/'result.json')
    decoded, cost = _plan_evidence(case, directory)
    if (row['case'] != case['case'] or row['preparation'] != case['preparation']
            or row['artifacts'] != _artifacts(directory) or row['decoded'] != frozen(directory/'decoded.json')
            or read(row['decoded']['path']) != decoded or row['status'] != decoded['status']
            or any(row[key] != value for key, value in cost.items())):
        raise ValueError('Planning result differs from raw provider evidence')
    return row


def _verified_plan(root):
    protocol = _verify_planning_protocol(root)
    summary = harness._read_sealed(root/'summary.json')
    rows = [_plan_result(root, case) for case in protocol['cases']]
    receipts = [frozen(root/'cases'/case['case']/'planning/result.json') for case in protocol['cases']]
    if (summary['version'] != PLANNING_VERSION or summary['stage'] != 'complete'
            or summary['prepared'] != frozen(root/'prepared.json') or summary['trial_denominator'] != 17
            or summary['results'] != rows or summary['result_receipts'] != receipts
            or any(summary[key] != value for key, value in _totals(rows).items())):
        raise ValueError('Planning summary or totals changed')
    return protocol, summary


def plan(args):
    root = args.input
    with (root/'.planning.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        protocol = _verify_planning_protocol(root)
        if (root/'summary.json').exists():
            return _verified_plan(root)[1]
        rows = []
        deadline = admission._deadline(protocol['deadline_utc'])
        for case in protocol['cases']:
            directory = root/'cases'/case['case']/'planning'
            if (directory/'result.json').exists():
                rows.append(_plan_result(root, case))
                continue
            withheld = None
            if case['request']:
                request = read(case['request']['path'])
                claim = directory/'dispatch_claim.json'
                if not claim.exists():
                    if (directory/'completion/manifest.json').exists():
                        raise ValueError('Planning manifest without dispatch claim')
                    totals = _totals(rows)
                    reservation = _reservation(request)
                    if totals['accounted_calls'] >= PLANNING_POLICY['max_calls'] or totals['accounted_tokens']+reservation > PLANNING_POLICY['max_total_tokens']:
                        withheld = 'planning_budget'
                    elif (deadline-datetime.now(timezone.utc)).total_seconds() < 300:
                        withheld = 'deadline'
                    else:
                        write(claim, dict(request=case['request'], reserved_calls=1,
                            reserved_tokens=reservation, created_utc=datetime.now(timezone.utc).isoformat()))
                        try:
                            dispatch(request, directory/'completion', root=ROOT)
                        except Exception as exc:
                            write(directory/'dispatch_exception.json', dict(exception_type=type(exc).__name__))
            decoded, cost = _plan_evidence(case, directory)
            write(directory/'decoded.json', decoded)
            row = dict(case=case['case'], preparation=case['preparation'], decoded=frozen(directory/'decoded.json'),
                status=decoded['status'], dispatch_withheld_reason=withheld, artifacts=_artifacts(directory), **cost)
            write(directory/'result.json', row)
            rows.append(row)
        summary = dict(version=PLANNING_VERSION, stage='complete', prepared=frozen(root/'prepared.json'),
            trial_denominator=17, results=rows,
            result_receipts=[frozen(root/'cases'/case['case']/'planning/result.json') for case in protocol['cases']],
            native_executions=0, **_totals(rows))
        write(root/'summary.json', summary)
        write(root/'summary_seal.json', frozen(root/'summary.json'))
        return _verified_plan(root)[1]


def prepare_generation(args):
    planning_root = args.input.resolve()
    protocol, summary = _verified_plan(planning_root)
    previous = read(protocol['inherited_prepared']['path'])
    args.output.mkdir(parents=True, exist_ok=False)
    cases = []
    for case, row in zip(protocol['cases'], summary['results']):
        old = case['inherited_case']
        inherited = read(old['generation']['path'])
        prepared = planning.generation_preparation(inherited, read(case['preparation']['path']), read(row['decoded']['path']))
        directory = args.output/'cases'/case['case']/'generation'
        write(directory/'preparation.json', prepared)
        if prepared['request']:
            write(directory/'request.json', prepared['request'])
        cases.append(dict(old, generation=frozen(directory/'preparation.json'),
            generation_request=frozen(directory/'request.json') if prepared['request'] else None,
            inherited_generation=old['generation'], planning_preparation=case['preparation'],
            planning_result=frozen(planning_root/'cases'/case['case']/'planning/result.json'),
            planning_decoded=row['decoded'], candidates=[], status='planned_generation_prepared'))
    admission._preload_local_imports(sys.modules[__name__])
    engine = _engine()
    record = dict(previous, version=VERSION, policy=relation.POLICY, cases=cases,
        algorithm=admission._loaded_sources(), algorithm_entrypoints=engine['_entrypoints'](),
        source_cohort=protocol['inherited_prepared'], planning_root=str(planning_root),
        planning_protocol=frozen(planning_root/'prepared.json'), planning_summary=frozen(planning_root/'summary.json'),
        planning_policy=PLANNING_POLICY, planning_costs=_totals(summary['results']),
        deadline_utc=protocol['deadline_utc'],
        comparative_limits=[*previous['comparative_limits'],
            'Extra declaration-ID planning stage with independent measured/reserved cost. Not a pure catalog-order or cost ablation.',
            'Same complete inherited anchors/context bundles, omissions, one generation call and at most three proposals. No omitted-anchor recovery.',
            'A selected nonempty catalog replaces the original catalog; unknown/empty planning retains the original catalog.',
            'Fresh review keeps R18 candidate-specific original-source enrichment. Source provenance is attached before review.'],
        created_utc=datetime.now(timezone.utc).isoformat())
    _verify_protocol(record, 'generation')
    engine['_verify_algorithm'](record)
    write(args.output/'prepared.json', record)
    write(args.output/'seal.json', frozen(args.output/'prepared.json'))
    return dict(prepared=frozen(args.output/'prepared.json'), trials=17,
        requests=sum(bool(c['generation_request']) for c in cases),
        planning_costs=record['planning_costs'], new_provider_calls=0, native_executions=0)


def generate(args):
    return _engine()['generate'](args)


def review_all(args):
    return _engine()['review_all'](args)


def run(args):
    result = _engine()['run'](args)
    protocol = read(args.input/'prepared.json')
    accounting = dict(native_summary=frozen(args.input/'summary.json'),
        planning_summary=protocol['planning_summary'], planning_costs=protocol['planning_costs'],
        generation_summary=protocol['generation_summary'], semantic_summary=frozen(args.input/'semantic_summary.json'),
        interpretation='Planning, generation and semantic-review costs remain separate; planning is never free or credited back.')
    write(args.input/'planning_accounting.json', accounting)
    return dict({key: value for key, value in result.items() if key != 'results'}, planning_model_calls=protocol['planning_costs']['provider_calls'],
        planning_measured_tokens=protocol['planning_costs']['measured_tokens'],
        planning_accounting=frozen(args.input/'planning_accounting.json'))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('stage', choices=['prepare', 'plan', 'prepare-generation', 'generate', 'review', 'run'])
    parser.add_argument('--source-cohort', type=Path)
    parser.add_argument('--input', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--deadline-utc')
    args = parser.parse_args()
    if args.stage == 'prepare' and not all((args.source_cohort, args.output, args.deadline_utc)):
        parser.error('prepare requires --source-cohort, --output and --deadline-utc')
    if args.stage != 'prepare' and args.input is None:
        parser.error('--input is required')
    if args.stage == 'prepare-generation' and args.output is None:
        parser.error('prepare-generation requires --output')
    action = {'prepare': prepare, 'plan': plan, 'prepare-generation': prepare_generation,
              'generate': generate, 'review': review_all, 'run': run}[args.stage]
    result = action(args)
    print(json.dumps({key: value for key, value in result.items() if key != 'results'}))
