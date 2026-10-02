"""Mocked sequential schedules with real runner budget/resume accounting."""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import run_sequential_admission as scheduler


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))


def setup(tmp_path, monkeypatch, cases=None, **overrides):
    cases = cases or {'A': ['a1', 'a2'], 'B': ['b1', 'b2']}
    now = [datetime(2026, 10, 2, tzinfo=timezone.utc)]
    monkeypatch.setattr(scheduler, '_now', lambda: now[0])
    monkeypatch.setattr(scheduler.runner, '_utc_now', lambda: now[0])
    monkeypatch.setattr(scheduler, '_seal_algorithm', lambda method: {})
    corpus, frontend, candidates = (tmp_path / name for name in ('corpus.json', 'frontend.json', 'candidates.json'))
    write(corpus, {'sources': {}})
    write(frontend, {})
    write(candidates, [{'id': identifier} for identifiers in cases.values() for identifier in identifiers])
    issue = tmp_path / 'issue.md'
    issue.write_text('Authored contract')
    records = [dict(case=case, candidate_id=identifier, key=case + ':' + identifier,
                    inputs={name: scheduler.frozen(path) for name, path in
                            [('corpus', corpus), ('frontend', frontend), ('candidates', candidates)]})
               for case, identifiers in cases.items() for identifier in identifiers]
    baseline = tmp_path / 'baseline.json'
    write(baseline, dict(controlled_failures=records, forbidden_truth={'must': 'never be selected'}))
    frontier = tmp_path / 'frontier'
    write(frontier / 'manifest.json', dict(protocol=dict(policy=dict(version=scheduler.RANKING_VERSION),
        policy_sha256='authored-policy', source_inventory=scheduler.frozen(baseline)),
        cases=[dict(case=case) for case in reversed(cases)]))
    for case, identifiers in cases.items():
        write(frontier / (case + '.json'), dict(case=case, policy_sha256='authored-policy',
            issue=scheduler.frozen(issue), ranking=[dict(id=identifier, rank=index)
                                                   for index, identifier in enumerate(identifiers, 1)]))
    values = dict(input=baseline, frontier=frontier, output=tmp_path / 'run', max_per_case=16,
                  max_attempts=20, max_model_calls=20, max_total_tokens=10000, max_prompt_bytes=64000,
                  output_token_limit=100, method='compact', thinking='disabled', reasoning_effort=None,
                  enrich_repository_sources=False, deadline_utc=(now[0] + timedelta(hours=2)).isoformat())
    values.update(overrides)
    args = SimpleNamespace(**values)
    scheduler.prepare(args)
    return args, now


def mocked_runner(monkeypatch, outcomes=None, *, usage=25, no_request=(), after_prepare=None,
                  crash_after_receipt=False):
    outcomes = outcomes or {}
    prepared, dispatched = [], []

    def prepare(args):
        record = scheduler.read(args.input)['controlled_failures'][0]
        identifier = record['candidate_id']
        prepared.append(identifier)
        item = args.output / 'item_0000'
        item.mkdir(parents=True)
        analysis = item / 'analysis.json'
        write(analysis, dict(status='unknown_prompt_budget' if identifier in no_request else 'prepared'))
        request_path = item / 'request.json'
        if identifier not in no_request:
            write(request_path, dict(id=identifier, system='S', prompt='P', max_tokens=args.output_token_limit))
        item_record = dict(name='item_0000', key=record['key'], case=record['case'], candidate_id=identifier,
            analysis_path=str(analysis), request_path=str(request_path) if request_path.exists() else None,
            request_sha256=scheduler.runner.digest(request_path) if request_path.exists() else None)
        write(args.output / 'prepared.json', dict(items=[item_record], max_model_calls=args.max_model_calls,
            max_total_tokens=args.max_total_tokens, deadline_utc=args.deadline_utc,
            method_module=scheduler.runner.METHODS[args.method], experiment='authored sequential schedule',
            baseline=scheduler.frozen(args.input)))
        if after_prepare:
            after_prepare()

    def dispatch(request, output, root):
        dispatched.append(request['id'])
        write(output / 'manifest.json', dict(status='complete', external_model_calls=1,
            request_id=request['id'], finish_reason='stop', usage=None if usage is None else dict(total_tokens=usage)))
        (output / 'completion.txt').write_text('{}')
        if crash_after_receipt:
            raise SystemExit('authored interruption after receipt')

    def decide(request, text, **kwargs):
        outcome = outcomes.get(request['id'], 'unknown')
        return dict(status={'supported': 'semantic_supported', 'rejected': 'semantic_rejected',
                            'unknown': 'unknown'}[outcome], alarm_eligible=outcome == 'supported')

    monkeypatch.setattr(scheduler.runner, 'prepare', prepare)
    monkeypatch.setattr(scheduler.runner, 'dispatch', dispatch)
    monkeypatch.setattr(scheduler.runner, '_method', lambda name: SimpleNamespace(decide=decide))
    return prepared, dispatched


def execute(args):
    return scheduler.run(SimpleNamespace(input=args.output))


def test_first_support_stops_case_even_when_external_truth_would_disagree(tmp_path, monkeypatch):
    args, _ = setup(tmp_path, monkeypatch)
    # This independent truth is deliberately never passed to the scheduler.
    independent_truth = {'a1': 'invalid', 'a2': 'valid'}
    prepared, calls = mocked_runner(monkeypatch, {'a1': 'supported', 'a2': 'supported',
                                                 'b1': 'rejected', 'b2': 'supported'})
    result = execute(args)
    assert calls == prepared == ['a1', 'b1', 'b2']
    assert result['counts'] == dict(pending=1, unknown=0, rejected=1, supported=2)
    assert result['outputs'][0]['candidate_id'] == 'a1'
    assert independent_truth[result['outputs'][0]['candidate_id']] == 'invalid'
    assert result['provider_calls'] == 3 and result['measured_tokens'] == 75
    assert result['reserved_tokens'] == 0


def test_round_robin_is_sorted_fair_and_pops_fixed_source_order(tmp_path, monkeypatch):
    args, _ = setup(tmp_path, monkeypatch, cases={'C': ['c2', 'c1'], 'A': ['a2', 'a1'], 'B': ['b2', 'b1']})
    _, calls = mocked_runner(monkeypatch)
    result = execute(args)
    assert calls == ['a2', 'b2', 'c2', 'a1', 'b1', 'c1']
    assert result['counts'] == dict(pending=0, unknown=6, rejected=0, supported=0)


def test_only_controlled_pool_is_accessed_and_freeze_precedes_preparation(tmp_path, monkeypatch):
    original_read = scheduler.read
    accesses = []

    class PoolOnly(dict):
        def __getitem__(self, key):
            accesses.append(key)
            if key != 'controlled_failures':
                raise AssertionError('Evaluation labels accessed')
            return super().__getitem__(key)

    def guarded_read(path):
        value = original_read(path)
        return PoolOnly(value) if Path(path).name == 'baseline.json' else value

    monkeypatch.setattr(scheduler, 'read', guarded_read)
    args, _ = setup(tmp_path, monkeypatch)
    assert accesses == ['controlled_failures']
    assert (args.output / 'seal.json').exists()
    assert not (args.output / 'attempts').exists()


def test_global_call_cap_and_per_case_cap_leave_pending_separate(tmp_path, monkeypatch):
    args, _ = setup(tmp_path, monkeypatch, max_model_calls=2)
    _, calls = mocked_runner(monkeypatch)
    result = execute(args)
    assert calls == ['a1', 'b1']
    assert result['stop_reason'] == 'call_budget' and result['counts']['pending'] == 2
    second, _ = setup(tmp_path / 'second', monkeypatch, max_per_case=1)
    _, calls = mocked_runner(monkeypatch)
    result = execute(second)
    assert calls == ['a1', 'b1'] and result['counts']['pending'] == 2


def test_no_request_attempts_are_bounded_without_provider_or_retry(tmp_path, monkeypatch):
    args, _ = setup(tmp_path, monkeypatch, max_attempts=2)
    prepared, calls = mocked_runner(monkeypatch, no_request={'a1', 'b1', 'a2', 'b2'})
    result = execute(args)
    assert prepared == ['a1', 'b1'] and calls == []
    assert result['counts'] == dict(pending=2, unknown=2, rejected=0, supported=0)
    assert result['stop_reason'] == 'attempt_budget'
    assert execute(args) == result and prepared == ['a1', 'b1']


def test_missing_usage_is_reserved_and_never_reported_as_measured_tokens(tmp_path, monkeypatch):
    args, _ = setup(tmp_path, monkeypatch, max_total_tokens=400)
    _, calls = mocked_runner(monkeypatch, usage=None)
    result = execute(args)
    assert calls == ['a1']
    assert result['provider_calls'] == 1 and result['reserved_calls'] == 0
    assert result['measured_tokens'] == 0 and result['reserved_tokens'] == 358
    assert result['accounted_tokens'] == 358 and result['usage_missing'] == 1
    assert result['counts']['unknown'] == 4


def test_byte_reservation_blocks_dispatch_before_spending(tmp_path, monkeypatch):
    args, _ = setup(tmp_path, monkeypatch, max_total_tokens=10, max_attempts=1)
    _, calls = mocked_runner(monkeypatch)
    result = execute(args)
    assert calls == [] and result['accounted_tokens'] == result['accounted_calls'] == 0
    assert result['counts']['unknown'] == 1 and result['counts']['pending'] == 3
    assert not list(args.output.rglob('dispatch_claim.json'))


def test_deadline_blocks_heavy_preparation_and_is_rechecked_after_prepare(tmp_path, monkeypatch):
    args, now = setup(tmp_path, monkeypatch)
    prepared, calls = mocked_runner(monkeypatch)
    now[0] += timedelta(hours=2, seconds=-299)
    result = execute(args)
    assert prepared == calls == [] and result['counts']['pending'] == 4
    second, clock = setup(tmp_path / 'second', monkeypatch)
    clock[0] += timedelta(hours=2, seconds=-301)
    def advance():
        clock[0] += timedelta(seconds=2)
    prepared, calls = mocked_runner(monkeypatch, after_prepare=advance)
    result = execute(second)
    assert prepared == ['a1'] and calls == []
    assert result['counts']['unknown'] == 1 and result['stop_reason'] == 'deadline'
    assert result['reserved_calls'] == 0


def test_resume_completed_receipts_never_repeats_calls_or_alters_output(tmp_path, monkeypatch):
    args, _ = setup(tmp_path, monkeypatch)
    prepared, calls = mocked_runner(monkeypatch, {'a1': 'supported', 'b1': 'supported'})
    first = execute(args)
    assert execute(args) == first
    assert calls == prepared == ['a1', 'b1']
    request = next(args.output.rglob('request.json'))
    request.write_text(request.read_text() + '\n')
    with pytest.raises(ValueError, match='Immutable attempt receipts changed'):
        execute(args)
    assert calls == ['a1', 'b1']


def test_resume_after_provider_receipt_uses_it_without_a_second_dispatch(tmp_path, monkeypatch):
    args, _ = setup(tmp_path, monkeypatch, max_model_calls=1)
    prepared, calls = mocked_runner(monkeypatch, {'a1': 'supported'}, crash_after_receipt=True)
    with pytest.raises(SystemExit):
        execute(args)
    result = execute(args)
    assert calls == prepared == ['a1']
    assert result['outputs'][0]['candidate_id'] == 'a1'
    assert result['provider_calls'] == 1 and result['reserved_calls'] == 0


def test_claim_without_receipt_is_unknown_reserved_and_never_retried(tmp_path, monkeypatch):
    args, _ = setup(tmp_path, monkeypatch, max_model_calls=1)
    prepared, calls = mocked_runner(monkeypatch)
    original_run = scheduler.runner.run
    def interrupt(args):
        raise SystemExit('authored interruption before receipt')
    monkeypatch.setattr(scheduler.runner, 'run', interrupt)
    with pytest.raises(SystemExit):
        execute(args)
    monkeypatch.setattr(scheduler.runner, 'run', original_run)
    result = execute(args)
    assert calls == [] and prepared == ['a1']
    assert result['provider_calls'] == 0 and result['reserved_calls'] == 1
    assert result['measured_tokens'] == 0 and result['reserved_tokens'] == 358
    assert result['counts'] == dict(pending=3, unknown=1, rejected=0, supported=0)
    assert execute(args) == result and calls == []


def test_frozen_policy_and_source_inputs_cannot_change_on_resume(tmp_path, monkeypatch):
    args, _ = setup(tmp_path, monkeypatch)
    _, calls = mocked_runner(monkeypatch)
    prepared = args.output / 'prepared.json'
    value = scheduler.read(prepared)
    value['policy']['max_model_calls'] += 1
    write(prepared, value)
    with pytest.raises(ValueError, match='Frozen input or receipt changed'):
        execute(args)
    assert calls == []


def test_changed_source_input_is_rejected_before_any_preparation(tmp_path, monkeypatch):
    args, _ = setup(tmp_path, monkeypatch)
    prepared, calls = mocked_runner(monkeypatch)
    write(tmp_path / 'corpus.json', {'changed': True})
    with pytest.raises(ValueError, match='Frozen input or receipt changed'):
        execute(args)
    assert prepared == calls == []


def test_interrupted_source_preparation_is_consumed_once_as_unknown(tmp_path, monkeypatch):
    args, _ = setup(tmp_path, monkeypatch, max_attempts=1)
    calls = []
    def interrupt(options):
        calls.append(options.output)
        options.output.mkdir()
        raise SystemExit('authored interrupted source analysis')
    monkeypatch.setattr(scheduler.runner, 'prepare', interrupt)
    with pytest.raises(SystemExit):
        execute(args)
    result = execute(args)
    assert len(calls) == 1
    assert result['counts'] == dict(pending=3, unknown=1, rejected=0, supported=0)
    assert result['provider_calls'] == result['reserved_calls'] == result['accounted_tokens'] == 0
    assert execute(args) == result and len(calls) == 1
