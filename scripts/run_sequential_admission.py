"""Freeze and run a label-free, round-robin semantic-admission budget.

Each candidate uses run_test_admission.prepare/run in its own directory. The
first semantic-supported output stops its case permanently; independent truth
is deliberately absent. Existing native executions are linked, never rerun.
"""
from __future__ import annotations

import argparse
from collections import Counter
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import json
from pathlib import Path
import sys
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import run_test_admission as runner


VERSION = 'sequential-source-admission.v1'
RANKING_VERSION = 'edited-contract-call-priority-v1'
MIN_DISPATCH_SECONDS = 300
read, frozen, write_new = runner.read, runner.frozen, runner.write_new


def _now():
    return datetime.now(timezone.utc)


def _verify(receipt):
    if runner.digest(receipt['path']) != receipt['sha256']:
        raise ValueError('Frozen input or receipt changed: ' + receipt['path'])


def _seal_algorithm(method):
    module = runner._method(runner.METHODS[method])
    runner._preload_local_imports(module)
    return runner._loaded_sources()


def prepare(args):
    """Freeze policy and complete supplied rankings before any source analysis."""
    names = ('max_per_case', 'max_attempts', 'max_model_calls', 'max_total_tokens',
             'max_prompt_bytes', 'output_token_limit')
    for name in names:
        value = getattr(args, name)
        if type(value) is not int or value < 0:
            raise ValueError(name + ' must be a nonnegative integer')
    if not 1 <= args.output_token_limit <= 16384 or args.max_prompt_bytes < 1:
        raise ValueError('Invalid prompt/output budget')
    if args.method not in runner.METHODS:
        raise ValueError('Unsupported admission method')
    deadline = runner._deadline(args.deadline_utc)
    if deadline is None:
        raise ValueError('A frozen deadline is required')
    baseline = frozen(args.input)
    # Only this section participates. All other baseline sections are ignored.
    records = read(args.input)['controlled_failures']
    frontier_path = Path(args.frontier) / 'manifest.json'
    frontier = read(frontier_path)
    protocol = frontier['protocol']
    if protocol['policy']['version'] != RANKING_VERSION:
        raise ValueError('Unsupported source ranking')
    if protocol['source_inventory'] != baseline:
        raise ValueError('Source ranking refers to a different baseline')
    occurrences = {}
    for row in records:
        occurrences.setdefault((row['case'], row['candidate_id']), row)
    inputs = {baseline['path']: baseline, str(frontier_path.resolve()): frozen(frontier_path)}
    cases, inventory = [], []
    case_names = [row['case'] for row in frontier['cases']]
    if len(set(case_names)) != len(case_names) or set(case_names) != {key[0] for key in occurrences}:
        raise ValueError('Ranking cases differ from the controlled pool')
    for case in sorted(case_names):
        case_path = (Path(args.frontier) / (case + '.json')).resolve()
        if case_path.parent != Path(args.frontier).resolve():
            raise ValueError('Invalid case artifact path')
        ranking = read(case_path)
        if ranking['case'] != case or ranking['policy_sha256'] != protocol['policy_sha256']:
            raise ValueError('Case ranking policy differs')
        rows = ranking['ranking']
        ids = [row['id'] for row in rows]
        if len(set(ids)) != len(ids) or set(ids) != {key[1] for key in occurrences if key[0] == case}:
            raise ValueError('Ranking must contain every source candidate exactly once')
        if [row['rank'] for row in rows] != list(range(1, len(rows) + 1)):
            raise ValueError('Ranking order must be complete and contiguous')
        inputs[str(case_path)] = frozen(case_path)
        inputs[ranking['issue']['path']] = ranking['issue']
        ordered = []
        for rank, identifier in enumerate(ids, 1):
            record = occurrences[case, identifier]
            issue_path = Path(record['inputs']['corpus']['path']).resolve().with_name('issue.md')
            if issue_path != Path(ranking['issue']['path']).resolve():
                raise ValueError('Ranking issue differs from the admission issue input')
            ordered.append(dict(rank=rank, candidate_id=identifier, key=record['key']))
            inventory.append(record)  # exact occurrence retained for the independent receipt auditor
            for name in ('corpus', 'frontend', 'candidates'):
                receipt = record['inputs'][name]
                previous = inputs.setdefault(receipt['path'], receipt)
                if previous != receipt:
                    raise ValueError('Conflicting source input hashes')
        cases.append(dict(case=case, ranking=ordered))
    for receipt in inputs.values():
        _verify(receipt)
    algorithm = _seal_algorithm(args.method)
    policy = {name: getattr(args, name) for name in names}
    policy.update(method=args.method, thinking=args.thinking, reasoning_effort=args.reasoning_effort,
                  enrich_repository_sources=args.enrich_repository_sources,
                  deadline_utc=deadline.isoformat(), minimum_dispatch_seconds=MIN_DISPATCH_SECONDS,
                  ordering='sorted_cases_round_robin_source_rank', stop='first_semantic_supported_per_case',
                  interrupted_dispatch='unknown_and_conservative_reservation_no_retry')
    if policy['thinking'] not in {'disabled', 'enabled'} or policy['reasoning_effort'] not in {None, 'low', 'high', 'max'}:
        raise ValueError('Unsupported provider settings')
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=False)
    inventory_path = output / 'inventory.json'
    write_new(inventory_path, dict(controlled_failures=inventory, source_inventory=baseline,
        source_only_ranking=True, selected_without_positive_or_review_labels=True))
    manifest = dict(version=VERSION, policy=policy, cases=cases, source_inputs=list(inputs.values()),
                    algorithm=algorithm, inventory=frozen(inventory_path), source_inventory=baseline,
                    created_utc=_now().isoformat(), provider_calls=0, native_executions=0,
                    evaluation_labels_used=False, source_ranking_policy_sha256=protocol['policy_sha256'])
    write_new(output / 'prepared.json', manifest)
    write_new(output / 'seal.json', dict(prepared=frozen(output / 'prepared.json')))
    return dict(cases=len(cases), ranked_candidates=len(inventory), provider_calls=0)


@contextmanager
def _exclusive(output):
    with (output / '.run.lock').open('a') as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise ValueError('Sequential scheduler is already running') from error
        try:
            yield
        finally:
            fcntl.flock(stream, fcntl.LOCK_UN)


def _artifacts(directory):
    return {str(path.relative_to(directory)): runner.digest(path)
            for path in sorted(directory.rglob('*')) if path.is_file() and path != directory / 'result.json'}


def _outcome(decision):
    if decision.get('status') == 'semantic_supported' and decision.get('alarm_eligible') is True:
        return 'supported'
    return 'rejected' if decision.get('status') == 'semantic_rejected' else 'unknown'


def _remaining(policy):
    return (runner._deadline(policy['deadline_utc']) - _now()).total_seconds()


def _next(cases, results, maximum):
    counts = Counter(row['selection']['case'] for row in results)
    solved = {row['selection']['case'] for row in results if row['outcome'] == 'supported'}
    names = [row['case'] for row in cases]
    start = (names.index(results[-1]['selection']['case']) + 1) % len(names) if results and names else 0
    for offset in range(len(names)):
        case = cases[(start + offset) % len(names)]
        count = counts[case['case']]
        if case['case'] not in solved and count < min(maximum, len(case['ranking'])):
            return dict(case=case['case'], **case['ranking'][count])
    return None


def _totals(results):
    fields = ('provider_calls', 'reserved_calls', 'measured_tokens', 'reserved_tokens', 'usage_missing')
    total = {field: sum(row.get(field, 0) for row in results) for field in fields}
    total.update(accounted_calls=total['provider_calls'] + total['reserved_calls'],
                 accounted_tokens=total['measured_tokens'] + total['reserved_tokens'])
    return total


def _finish(directory, selection, *, summary=None, reason=None, unreceipted=None):
    if summary is not None:
        if len(summary['decisions']) != 1:
            raise ValueError('Each admission subrun must contain exactly one candidate')
        row = summary['decisions'][0]
        if (row['key'], row['case'], row['candidate_id']) != tuple(selection[key] for key in ('key', 'case', 'candidate_id')):
            raise ValueError('Admission result differs from frozen selection')
        decision = row['decision']
        calls, accounted, missing = (summary[name] for name in ('provider_calls', 'accounted_tokens', 'usage_missing'))
        if any(type(value) is not int or value < 0 for value in (calls, accounted, missing)):
            raise ValueError('Invalid runner cost accounting')
        measured, reserved = (0, accounted) if missing else (accounted, 0)
    else:
        decision = dict(status='unknown', alarm_eligible=False, reason=reason)
        calls = measured = reserved = missing = 0
    unreceipted = unreceipted or dict(calls=0, tokens=0)
    result = dict(selection=selection, outcome=_outcome(decision), decision=decision,
                  provider_calls=calls, reserved_calls=unreceipted['calls'], measured_tokens=measured,
                  reserved_tokens=reserved + unreceipted['tokens'],
                  usage_missing=missing + bool(unreceipted['calls']), artifacts=_artifacts(directory))
    write_new(directory / 'result.json', result)
    return result


def _attempt(directory, selection, record, prepared, totals, *, resumed):
    policy = prepared['policy']
    admission = directory / 'admission'
    if not (admission / 'prepared.json').exists():
        if resumed and admission.exists():
            return _finish(directory, selection, reason='interrupted_source_preparation')
        if _remaining(policy) < MIN_DISPATCH_SECONDS:
            return _finish(directory, selection, reason='deadline_before_source_preparation')
        inventory_path = directory / 'inventory.json'
        if not inventory_path.exists():
            write_new(inventory_path, dict(controlled_failures=[record], source_inventory=prepared['source_inventory'],
                                          source_only_ranking=True, selected_without_positive_or_review_labels=True))
        options = dict(input=inventory_path, output=admission, scope='all',
                       max_model_calls=1, max_total_tokens=policy['max_total_tokens'] - totals['accounted_tokens'])
        options.update({name: policy[name] for name in ('method', 'thinking', 'reasoning_effort',
                       'enrich_repository_sources', 'max_prompt_bytes', 'output_token_limit', 'deadline_utc')})
        runner.prepare(SimpleNamespace(**options))
    subrun = read(admission / 'prepared.json')
    if len(subrun['items']) != 1:
        raise ValueError('Prepared admission must contain exactly one candidate')
    item = subrun['items'][0]
    if (item['key'], item['case'], item['candidate_id']) != tuple(selection[key] for key in ('key', 'case', 'candidate_id')):
        raise ValueError('Prepared admission differs from selection')
    item_directory = admission / item['name']
    receipt = item_directory / 'completion' / 'manifest.json'
    claim_path = directory / 'dispatch_claim.json'
    unreceipted = None
    if receipt.exists() and not claim_path.exists():
        raise ValueError('Provider receipt has no scheduler dispatch claim')
    if claim_path.exists():
        claim = read(claim_path)
        if (not item['request_path'] or claim['request'] != frozen(item['request_path'])
                or claim['reserved_tokens'] != runner._token_upper_bound(read(item['request_path']))
                or claim['reserved_calls'] != 1):
            raise ValueError('Dispatch claim differs from frozen request')
        if not receipt.exists():
            decision_path = item_directory / 'decision.json'
            known_no_dispatch = (decision_path.exists()
                                 and read(decision_path).get('reason') in {'deadline', 'model_budget'})
            if not known_no_dispatch:
                unreceipted = dict(calls=1, tokens=claim['reserved_tokens'])
            if not decision_path.exists():
                # This immutable no-dispatch decision lets the existing runner
                # finish normal audit receipts without reissuing the request.
                write_new(decision_path, dict(status='unknown', alarm_eligible=False,
                    semantic_validity='unconfirmed', reason='interrupted_dispatch_without_receipt'))
    elif item['request_path']:
        request = read(item['request_path'])
        reservation = runner._token_upper_bound(request)
        if (reservation <= policy['max_total_tokens'] - totals['accounted_tokens']
                and _remaining(policy) >= MIN_DISPATCH_SECONDS):
            write_new(claim_path, dict(request=frozen(item['request_path']), reserved_tokens=reservation,
                                       reserved_calls=1, created_utc=_now().isoformat()))
    # Existing runner performs the final 300-second check immediately before
    # dispatch and enforces its frozen one-call and remaining-token budgets.
    runner.run(SimpleNamespace(input=admission, deadline_utc=policy['deadline_utc']))
    return _finish(directory, selection, summary=read(admission / 'summary.json'), unreceipted=unreceipted)


def run(args):
    output = Path(args.input)
    with _exclusive(output):
        seal = read(output / 'seal.json')
        _verify(seal['prepared'])
        prepared = read(output / 'prepared.json')
        if prepared['version'] != VERSION:
            raise ValueError('Unsupported scheduler version')
        runner.verify_seal(prepared['algorithm'])
        for receipt in [prepared['inventory'], *prepared['source_inputs']]:
            _verify(receipt)
        records = {row['key']: row for row in read(prepared['inventory']['path'])['controlled_failures']}
        policy, cases, results = prepared['policy'], prepared['cases'], []
        attempts = output / 'attempts'
        attempts.mkdir(exist_ok=True)
        paths = sorted(attempts.iterdir())
        for index, directory in enumerate(paths):
            if directory.name != f'attempt_{index:06d}' or not directory.is_dir():
                raise ValueError('Noncontiguous attempt trace')
            expected = _next(cases, results, policy['max_per_case'])
            selection = read(directory / 'selection.json')
            if selection != expected:
                raise ValueError('Attempt differs from frozen round-robin ranking')
            if (directory / 'result.json').exists():
                result = read(directory / 'result.json')
                if result['selection'] != selection or result['artifacts'] != _artifacts(directory):
                    raise ValueError('Immutable attempt receipts changed')
            else:
                if index != len(paths) - 1:
                    raise ValueError('Unfinished attempt before later attempts')
                result = _attempt(directory, selection, records[selection['key']], prepared, _totals(results), resumed=True)
            results.append(result)
        if (output / 'summary.json').exists():
            final = read(output / 'summary.json')
            _verify(final['prepared'])
            if final['attempt_receipts'] != [frozen(path / 'result.json') for path in paths]:
                raise ValueError('Frozen final summary differs from attempt receipts')
            return final
        reason = 'no_eligible_case'
        while (selection := _next(cases, results, policy['max_per_case'])) is not None:
            _verify(seal['prepared'])
            totals = _totals(results)
            if len(results) >= policy['max_attempts']:
                reason = 'attempt_budget'; break
            if totals['accounted_calls'] >= policy['max_model_calls']:
                reason = 'call_budget'; break
            if totals['accounted_tokens'] >= policy['max_total_tokens']:
                reason = 'token_budget'; break
            if _remaining(policy) < MIN_DISPATCH_SECONDS:
                reason = 'deadline'; break
            directory = attempts / f'attempt_{len(results):06d}'
            directory.mkdir()
            write_new(directory / 'selection.json', selection)
            result = _attempt(directory, selection, records[selection['key']], prepared, totals, resumed=False)
            results.append(result)
            print(json.dumps(dict(phase='sequential', attempt=len(results), case=selection['case'],
                                  rank=selection['rank'], outcome=result['outcome'], **_totals(results))), flush=True)
        _verify(seal['prepared'])
        counts = Counter(row['outcome'] for row in results)
        total_candidates = sum(len(case['ranking']) for case in cases)
        if reason == 'no_eligible_case':
            reason = ('source_frontier_exhausted' if len(results) == total_candidates
                      else 'all_cases_supported' if counts['supported'] == len(cases)
                      else 'per_case_budget_or_source_exhausted')
        final = dict(version=VERSION, stage='complete', stop_reason=reason,
            prepared=frozen(output / 'prepared.json'), attempts=len(results),
            counts=dict(pending=total_candidates - len(results), unknown=counts['unknown'],
                        rejected=counts['rejected'], supported=counts['supported']),
            outputs=[dict(**row['selection'], decision=row['decision']) for row in results if row['outcome'] == 'supported'],
            attempt_receipts=[frozen(attempts / f'attempt_{index:06d}' / 'result.json') for index in range(len(results))],
            fresh_semantic_requests=True, native_executions=0, evaluation_labels_used=False,
            independent_validity='unconfirmed; no posthoc replacement or retry', **_totals(results))
        write_new(output / 'summary.json', final)
        return final


if __name__ == '__main__':
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('stage', choices=['prepare', 'run'])
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--frontier', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--max-per-case', type=int, default=16)
    parser.add_argument('--max-attempts', type=int, default=256)
    parser.add_argument('--max-model-calls', type=int, default=64)
    parser.add_argument('--max-total-tokens', type=int, default=500000)
    parser.add_argument('--max-prompt-bytes', type=int, default=64000)
    parser.add_argument('--output-token-limit', type=int, default=1024)
    parser.add_argument('--method', choices=sorted(runner.METHODS), default='compact')
    parser.add_argument('--thinking', choices=['disabled', 'enabled'], default='disabled')
    parser.add_argument('--reasoning-effort', choices=['low', 'high', 'max'])
    parser.add_argument('--deadline-utc')
    parser.add_argument('--enrich-repository-sources', action='store_true')
    options = parser.parse_args()
    if options.stage == 'prepare' and (options.frontier is None or options.output is None):
        parser.error('prepare requires --frontier and --output')
    print(json.dumps(prepare(options) if options.stage == 'prepare' else run(options)))
