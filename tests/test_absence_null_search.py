"""Semantic decisions are immutable gates before any native execution."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import hashlib
import json

import pytest

from scripts import run_absence_null_search as runner


def prepared(tmp_path, statuses=('support', 'reject'), max_calls=64):
    source = tmp_path/'source'; source.mkdir()
    for name in ('corpus.json', 'frontend.json', 'case.json', 'selection.json'):
        runner.write(source/name, {})
    (source/'issue.md').write_text('A public typed-field contract.')
    inputs = {name:runner.frozen(source/name) for name in
              ('corpus.json','frontend.json','case.json','selection.json','issue.md')}
    directory = tmp_path/'cases'/'generic'
    runner.write(directory/'generation.json', dict(status='source_hypotheses'))
    entries = []
    for rank, status in enumerate(statuses, 1):
        path = directory/f'candidate_{rank:04d}'
        runner.write(path/'program.json', dict(id='candidate_'+str(rank)))
        request = runner.admission._configure_request(dict(system='public-contract', prompt=status),
            SimpleNamespace(thinking='enabled', output_token_limit=16384, reasoning_effort='high'))
        runner.write(path/'review/analysis.json', dict(status='prepared'))
        runner.write(path/'review/request.json', request)
        entries.append(dict(rank=rank, program=runner.frozen(path/'program.json'),
            analysis=runner.frozen(path/'review/analysis.json'), request=runner.frozen(path/'review/request.json')))
    protocol = dict(version=runner.VERSION, algorithm={}, trial_denominator=1,
        cases=[dict(case='generic', source=str(source), inputs=inputs, source_context=None,
            generation=runner.frozen(directory/'generation.json'), status='source_hypotheses', candidates=entries)],
        max_native_executions=17, timeout=180,
        semantic_policy=dict(max_calls=max_calls, max_total_tokens=1000000),
        deadline_utc=(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat())
    runner.write(tmp_path/'prepared.json', protocol)
    runner.write(tmp_path/'seal.json', runner.frozen(tmp_path/'prepared.json'))
    return SimpleNamespace(input=tmp_path), protocol


def fake_provider(calls):
    def dispatch(request, output, *, root):
        calls.append(request['prompt']); output.mkdir()
        runner.write(output/'request.json', dict(
            messages=[dict(role='system', content=request['system']),
                      dict(role='user', content=request['prompt'])],
            max_tokens=request['max_tokens'], thinking=dict(type=request['thinking']),
            reasoning_effort=request['reasoning_effort'], model='test-model'))
        raw = dict(model='test-model', usage=dict(total_tokens=100),
                   choices=[dict(message=dict(content=request['prompt']), finish_reason='stop')])
        body = json.dumps(raw).encode()
        (output/'response.body').write_bytes(body)
        runner.write(output/'response.json', raw)
        runner.write(output/'manifest.json', dict(status='complete', external_model_calls=1,
            request_id=request['id'], request_sha256=runner.admission.digest(output/'request.json'),
            response_sha256=hashlib.sha256(body).hexdigest(), model='test-model', response_model='test-model',
            finish_reason='stop', usage=dict(total_tokens=100)))
        (output/'completion.txt').write_text(request['prompt'])
    return dispatch


def decision(request, text, **kwargs):
    return dict(status='semantic_supported' if text=='support' else 'semantic_rejected',
                alarm_eligible=text=='support')


def test_all_frozen_candidates_are_reviewed_before_native_and_only_supported_execute(tmp_path, monkeypatch):
    args, protocol = prepared(tmp_path, ('reject', 'support', 'support'))
    calls = []; native = []
    monkeypatch.setattr(runner, 'dispatch', fake_provider(calls))
    monkeypatch.setattr(runner.review, 'decide', decision)
    result = runner.review_all(args)
    assert calls == ['reject', 'support', 'support'] and result['admitted'] == 2
    def one_run(candidate, source, corpus, target, protocol):
        native.append(candidate['id'])
        assert len(calls) == 3
        outcome = dict(transport=dict(status='matched'), native=dict(
            controls=dict(status='all_source_controls_passed'), controlled_failure=True))
        runner.write(target/'outcome.json', outcome)
        return outcome
    monkeypatch.setattr(runner, 'one_run', one_run)
    assert runner.run(args)['detector_alerts'] == 1
    assert native == ['candidate_2', 'candidate_2']
    summary = runner.read(tmp_path/'summary.json')
    assert summary['results'][0]['alert']['program'] == protocol['cases'][0]['candidates'][1]['program']
    assert runner.review_all(args) == result and len(calls) == 3


def test_call_budget_and_interrupted_claim_never_execute_or_retry(tmp_path, monkeypatch):
    args, protocol = prepared(tmp_path, ('support', 'support'), max_calls=1)
    entry = protocol['cases'][0]['candidates'][0]
    request = runner.read(entry['request']['path'])
    folder = tmp_path/'cases/generic/candidate_0001/review'
    runner.write(folder/'dispatch_claim.json', dict(request=entry['request'],
        reserved_tokens=runner._reservation(request), reserved_calls=1))
    calls = []; monkeypatch.setattr(runner, 'dispatch', fake_provider(calls))
    monkeypatch.setattr(runner.review, 'decide', decision)
    result = runner.review_all(args)
    assert result['reserved_calls'] == 1 and result['admitted'] == 0 and not calls
    monkeypatch.setattr(runner, 'one_run', lambda *a, **k: pytest.fail('Unknown candidate executed'))
    assert runner.run(args)['detector_alerts'] == 0
    assert runner.review_all(args) == result and not calls


def test_native_refuses_missing_semantic_phase(tmp_path):
    args, _ = prepared(tmp_path)
    with pytest.raises(FileNotFoundError): runner.run(args)


@pytest.mark.parametrize('artifact', ['program', 'decision', 'completion'])
def test_changed_review_or_candidate_cannot_authorize_native(tmp_path, monkeypatch, artifact):
    args, protocol = prepared(tmp_path, ('support',))
    monkeypatch.setattr(runner, 'dispatch', fake_provider([]))
    monkeypatch.setattr(runner.review, 'decide', decision)
    runner.review_all(args)
    directory = tmp_path/'cases/generic/candidate_0001'
    path = {'program':directory/'program.json', 'decision':directory/'review/decision.json',
            'completion':directory/'review/completion/completion.txt'}[artifact]
    path.write_text(path.read_text()+' ')
    monkeypatch.setattr(runner, 'one_run', lambda *a, **k: pytest.fail('Changed review authorized execution'))
    with pytest.raises(ValueError): runner.run(args)


def test_dispatch_exception_is_reserved_without_secret_or_retry(tmp_path, monkeypatch):
    args, _ = prepared(tmp_path, ('support',))
    calls = []
    def broken(*a, **k):
        calls.append(1); raise RuntimeError('PRIVATE_ENDPOINT')
    monkeypatch.setattr(runner, 'dispatch', broken)
    result = runner.review_all(args)
    assert result['reserved_calls'] == 1 and len(calls) == 1
    assert runner.review_all(args) == result and len(calls) == 1
    assert 'PRIVATE_ENDPOINT' not in (tmp_path/'cases/generic/candidate_0001/review/decision.json').read_text()
