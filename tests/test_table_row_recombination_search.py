"""Semantic decisions are immutable gates before any native execution."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import hashlib
import json
from pathlib import Path
import sys

import pytest

from scripts import run_table_row_recombination_search as runner
from anchor_retrieval.syntax import Source
from relational_gap.frontend import extract_frontend, to_emitter_corpus


TABLE_CODE = '''package sample
import ("testing"; "example.org/subject"; "github.com/stretchr/testify/require")
func TestPairs(t *testing.T) {
 rows := []struct{ left, right string }{
  {"α", "one"},
  {`bb`, "two"},
  {"ccc", "three"},
 }
 for _, row := range rows {
  got := subject.Combine(row.left, row.right)
  want := subject.Expected(row.right)
  require.Equal(t, want, got)
 }
}
'''


def source_cohort(tmp_path, count=17):
    repository = tmp_path/'repository'; repository.mkdir()
    (repository/'sample_test.go').write_text(TABLE_CODE)
    original = Source('sample_test.go', TABLE_CODE, 'go', 'repository')
    historical = Source('old_test.go', TABLE_CODE.replace('TestPairs', 'TestHistorical'), 'go', 'trajectory')
    frontend = extract_frontend([original, historical])
    corpus = to_emitter_corpus(frontend)
    cases = []
    for index in range(count):
        source = tmp_path/'sources'/str(index)
        # The other cases have no source hypotheses in this synthetic cohort.
        front = frontend if index == 0 else extract_frontend([Source('empty.py', 'x = 1\n', 'python', 'repository')])
        corp = corpus if index == 0 else to_emitter_corpus(front)
        runner.write(source/'corpus.json', corp)
        runner.write(source/'frontend.json', front)
        runner.write(source/'case.json', dict(repository=str(repository)))
        runner.write(source/'selection.json', {})
        (source/'issue.md').write_text('Combining values must preserve the documented result.')
        cases.append(dict(case=f'trial{index:02d}', source=str(source)))
    cohort = tmp_path/'cohort'
    # Old algorithms are not current executable dependencies. Only source paths
    # and the complete trial list enter this round.
    runner.write(cohort/'prepared.json', dict(cases=cases, algorithm=dict(unavailable_old_algorithm={})))
    runner.write(cohort/'seal.json', runner.frozen(cohort/'prepared.json'))
    return SimpleNamespace(source_cohort=cohort, output=tmp_path/'prepared',
        deadline_utc=(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat()), corpus, frontend


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
        entries.append(dict(rank=rank, order=[rank], program=runner.frozen(path/'program.json'),
            analysis=runner.frozen(path/'review/analysis.json'), request=runner.frozen(path/'review/request.json')))
    runner.admission._preload_local_imports(runner)
    protocol = dict(version=runner.VERSION, algorithm=runner.admission._loaded_sources(),
        algorithm_entrypoints={name:runner.frozen(path) for name,path in {
            'driver':runner.__file__, 'constructor':runner.relation.__file__, 'semantic_reviewer':runner.review.__file__,
            'native_adapter':sys.modules[runner.one_run.__module__].__file__,
            'provider_adapter':sys.modules[runner.dispatch.__module__].__file__}.items()},
        trial_denominator=1, max_candidates_per_trial=16,
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


def test_repository_projection_rebuilds_metadata_and_excludes_historical_tests(tmp_path):
    _, corpus, frontend = source_cohort(tmp_path)
    assert 'old_test.go' in corpus['sources']
    projected, projected_frontend, receipt = runner.repository_projection(corpus, frontend)
    assert set(projected['sources']) == {'sample_test.go'}
    assert projected['sources']['sample_test.go']['code'] == TABLE_CODE
    assert set(projected_frontend['sources']) == {'sample_test.go'}
    assert receipt['excluded_source_count'] == 1
    assert receipt['test_ids'] == sorted(projected['tests'])
    assert all(row['span']['path'] == 'sample_test.go' for row in projected['tests'].values())
    assert 'old_test.go' not in json.dumps(projected_frontend)
    assert 'TestHistorical' not in json.dumps(projected)


def test_prepare_freezes_all_seventeen_source_cases_and_complete_single_row_review(tmp_path):
    args, _, _ = source_cohort(tmp_path)
    result = runner.collect(args, freeze=True)
    assert result['trials'] == 17 and result['selected'] == 6
    protocol = runner.read(result['record']['path'])
    runner._verify_algorithm(protocol)
    assert protocol['max_candidates_per_trial'] == 16
    assert protocol['semantic_policy']['max_calls'] == 64
    assert protocol['semantic_policy']['max_total_tokens'] == 1000000
    assert protocol['semantic_policy']['reasoning_effort'] == 'high'
    assert protocol['external_model_calls'] == 0
    assert protocol['algorithm_entrypoints']['driver'] == runner.frozen(runner.__file__)
    assert protocol['algorithm_entrypoints']['native_adapter']['path'].endswith('/run_documented_default_search.py')
    assert protocol['algorithm_entrypoints']['provider_adapter']['path'].endswith('/relational_gap/provider.py')
    case = protocol['cases'][0]
    assert all(len(row['candidates']) == 0 for row in protocol['cases'][1:])
    runner._verify_case_inputs(case)
    entry = case['candidates'][0]
    candidate = runner.read(entry['program']['path'])
    assert len(candidate['edits']) == 1
    assert [e['role'] for e in candidate['edits']] == ['input']
    request = runner.read(entry['request']['path'])
    assert request['thinking'] == 'enabled' and request['reasoning_effort'] == 'high'
    assert request['id'] == runner.admission._request_identity(request)
    assert 'TestHistorical' not in request['prompt']
    assert 'require.Equal(t, want, got)' in request['prompt']
    payload = json.loads(request['prompt'])
    assert all(e['before'] in payload['original_test'] for e in candidate['edits'])
    assert all(e['after'] in payload['modified_test'] for e in candidate['edits'])
    assert list(args.output.rglob('manifest.json'))  # Projection receipt exists.
    assert not list(args.output.rglob('dispatch_claim.json'))
    assert not list(args.output.rglob('native_outcome.json'))


def test_incomplete_cohort_and_changed_source_seal_reject_before_output_creation(tmp_path):
    args, _, _ = source_cohort(tmp_path, count=16)
    with pytest.raises(ValueError, match='seventeen'):
        runner.collect(args, freeze=True)
    assert not args.output.exists()
    (args.source_cohort/'prepared.json').write_text('{}')
    with pytest.raises(ValueError, match='seal'):
        runner.collect(args, freeze=True)
    assert not args.output.exists()


def test_entrypoint_missing_from_import_seal_refuses_protocol(tmp_path):
    _, protocol = prepared(tmp_path)
    constructor = protocol['algorithm_entrypoints']['constructor']
    protocol['algorithm'] = {name: row for name, row in protocol['algorithm'].items() if row != constructor}
    with pytest.raises(ValueError, match='entrypoint missing'):
        runner._verify_algorithm(protocol)


def test_semantic_replay_rejects_forged_support_even_with_recomputed_outer_hashes(tmp_path, monkeypatch):
    args, protocol = prepared(tmp_path, ('reject',))
    monkeypatch.setattr(runner, 'dispatch', fake_provider([]))
    monkeypatch.setattr(runner.review, 'decide', decision)
    runner.review_all(args)
    directory = tmp_path/'cases/generic/candidate_0001/review'
    (directory/'decision.json').write_text(json.dumps(decision({}, 'support')))
    row = runner.read(directory/'result.json')
    row.update(decision=runner.frozen(directory/'decision.json'), status='semantic_supported',
               admitted=True, artifacts=runner._artifacts(directory))
    (directory/'result.json').write_text(json.dumps(row))
    summary = runner.read(tmp_path/'semantic_summary.json')
    summary.update(results=[row], result_receipts=[runner.frozen(directory/'result.json')], admitted=1)
    (tmp_path/'semantic_summary.json').write_text(json.dumps(summary))
    (tmp_path/'semantic_summary_seal.json').write_text(json.dumps(runner.frozen(tmp_path/'semantic_summary.json')))
    with pytest.raises(ValueError, match='raw provider response'):
        runner._verified_semantic(tmp_path, protocol)


@pytest.mark.parametrize('first,second,expected_count', [
    ('failure', 'pass', 2), ('source_failed', 'failure', 1), ('unmatched', 'pass', 2),
])
def test_native_stop_and_transport_gates(tmp_path, monkeypatch, first, second, expected_count):
    args, _ = prepared(tmp_path, ('support', 'support'))
    monkeypatch.setattr(runner, 'dispatch', fake_provider([]))
    monkeypatch.setattr(runner.review, 'decide', decision)
    runner.review_all(args)
    calls = []
    def execute(candidate, source, corpus, target, protocol):
        status = first if not calls else second
        calls.append(candidate['id'])
        outcome = dict(transport=dict(status='mismatch' if status == 'unmatched' else 'matched'),
            native=dict(controls=dict(status='failed' if status == 'source_failed' else 'all_source_controls_passed'),
                        controlled_failure=status in {'failure', 'unmatched'}))
        runner.write(target/'outcome.json', outcome)
        return outcome
    monkeypatch.setattr(runner, 'one_run', execute)
    assert runner.run(args)['detector_alerts'] == 0
    assert len(calls) == expected_count
    if first == 'failure':
        assert calls == ['candidate_1', 'candidate_1']
    elif first == 'unmatched':
        assert calls == ['candidate_1', 'candidate_2']
    # Resume replays outcome seals and the exact stop condition.
    assert runner.run(args)['detector_alerts'] == 0
    assert len(calls) == expected_count


def test_unsealed_cached_native_outcome_never_resumes(tmp_path):
    target = tmp_path/'initial'
    runner.write(target/'outcome.json', dict(transport=dict(status='matched')))
    with pytest.raises(FileNotFoundError):
        runner._native_once({}, tmp_path, {}, target, {})
