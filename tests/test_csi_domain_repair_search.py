from datetime import datetime, timedelta, timezone
import hashlib
import json
from types import SimpleNamespace

import pytest

from scripts import run_csi_domain_repair_search as runner


def test_harness_bindings_are_private_and_do_not_change_r12_globals():
    original_review, original_version = runner.harness.review, runner.harness.VERSION
    engine = runner._engine()
    assert engine['review'] is runner.review and engine['VERSION'] == runner.VERSION
    assert engine['_verified_semantic'].__globals__ is engine
    assert engine['_native_once'].__globals__ is engine
    assert engine['_review_entries'] is runner._review_entries
    assert runner.harness.review is original_review and runner.harness.VERSION == original_version
    assert engine['review'] is not runner.harness.review


def test_extra_value_transport_check_runs_before_subject_execution(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, 'try_emit', lambda *a: (tmp_path/'artifact', None))
    monkeypatch.setattr(runner.csi_repair_transport, 'verify', lambda *a: dict(status='mismatch', reason='wrong primary'))
    monkeypatch.setattr(runner, 'execute', lambda *a: pytest.fail('Mismatched input reached native'))
    outcome = runner.one_run({}, tmp_path, {}, tmp_path/'run', {})
    assert outcome['native'] is None and outcome['transport']['reason'] == 'wrong primary'


def setup(tmp_path):
    source = tmp_path/'source'
    for name in ('corpus.json', 'frontend.json', 'case.json', 'selection.json'):
        runner.write(source/name, {})
    (source/'issue.md').write_text('Public contract')
    inputs = {name: runner.frozen(source/name) for name in ('corpus.json', 'frontend.json', 'case.json', 'selection.json', 'issue.md')}
    cases = []
    for number, gates in enumerate([['unknown'], ['allow', 'allow']]):
        name = 'case'+str(number)
        directory = tmp_path/'cases'/name
        runner.write(directory/'generation.json', dict(status='source_hypotheses'))
        entries = []
        for rank, gate in enumerate(gates, 1):
            path = directory/f'candidate_{rank:04d}'
            runner.write(path/'program.json', dict(id=name+str(rank)))
            payload = dict(original_test='original whole test', modified_test='repaired whole test',
                           desired='reject' if number == 1 and rank == 1 else 'support')
            guard = dict(decision=gate, status='bounded_input_domain_checked' if gate == 'allow' else 'input_domain_or_binding_unproved',
                         allow_prior_gate=gate == 'allow', checks=[dict(value='packet', decision='allow',
                         positive_key_result=True, domain_binding=dict(doc='public CSI doc'))],
                         original_test_sha256=runner.relation.sha(payload['original_test']),
                         modified_test_sha256=runner.relation.sha(payload['modified_test']))
            metadata = dict(guard=guard, repaired_value='packet')
            request = runner.admission._configure_request(dict(system='Whole-test contract', prompt=json.dumps(payload),
                csi_repair_domain=metadata, csi_repair_domain_sha256=runner.relation.canonical_sha(metadata)),
                SimpleNamespace(thinking='enabled', reasoning_effort='high', output_token_limit=16384))
            runner.write(path/'review/request.json', request)
            runner.write(path/'review/analysis.json', dict(status='prepared'))
            entries.append(dict(rank=rank, order=[number*10+rank], program=runner.frozen(path/'program.json'),
                                analysis=runner.frozen(path/'review/analysis.json'), request=runner.frozen(path/'review/request.json')))
        cases.append(dict(case=name, source=str(source), inputs=inputs, candidates=entries,
                          generation=runner.frozen(directory/'generation.json'), source_context=None,
                          review_projection=None, status='source_hypotheses'))
    runner.admission._preload_local_imports(runner)
    protocol = dict(version=runner.VERSION, policy=runner.relation.POLICY, cases=cases,
        trial_denominator=2, max_candidates_per_trial=16, max_native_executions=6, timeout=180,
        construction_receipts=[], reused_harness=runner.frozen(runner.harness.__file__),
        deadline_utc=(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat(),
        semantic_policy=dict(max_calls=3, max_total_tokens=400000),
        algorithm=runner.admission._loaded_sources(),
        algorithm_entrypoints={name: runner.frozen(path) for name, path in dict(
            driver=runner.__file__, constructor=runner.relation.__file__, semantic_reviewer=runner.review.__file__,
            native_adapter=runner.__file__, provider_adapter=runner.harness.sys.modules[runner.dispatch.__module__].__file__).items()})
    runner.write(tmp_path/'prepared.json', protocol)
    runner.write(tmp_path/'seal.json', runner.frozen(tmp_path/'prepared.json'))
    return SimpleNamespace(input=tmp_path), protocol


def provider(calls):
    def dispatch(request, output, *, root):
        desired = json.loads(request['prompt'])['desired']
        calls.append(desired)
        output.mkdir()
        runner.write(output/'request.json', dict(messages=[dict(role='system', content=request['system']),
            dict(role='user', content=request['prompt'])], max_tokens=request['max_tokens'],
            thinking=dict(type=request['thinking']), reasoning_effort=request['reasoning_effort'], model='test-model'))
        raw = dict(model='test-model', usage=dict(total_tokens=100), choices=[dict(message=dict(content=desired), finish_reason='stop')])
        body = json.dumps(raw).encode()
        (output/'response.body').write_bytes(body)
        runner.write(output/'response.json', raw)
        runner.write(output/'manifest.json', dict(status='complete', external_model_calls=1, request_id=request['id'],
            request_sha256=runner.admission.digest(output/'request.json'), response_sha256=hashlib.sha256(body).hexdigest(),
            model='test-model', response_model='test-model', finish_reason='stop', usage=dict(total_tokens=100)))
        (output/'completion.txt').write_text(desired)
    return dispatch


def test_all_three_fresh_reviews_precede_native_and_unknown_domain_never_executes(tmp_path, monkeypatch):
    args, protocol = setup(tmp_path)
    calls, native = [], []
    monkeypatch.setattr(runner, 'dispatch', provider(calls))
    monkeypatch.setattr(runner.review.whole_test, 'decide', lambda request, response, **k:
        dict(status='semantic_supported' if response == 'support' else 'semantic_rejected', alarm_eligible=response == 'support'))
    result = runner.review_all(args)
    assert calls == ['support', 'reject', 'support']
    assert result['provider_calls'] == 3 and result['measured_tokens'] == 300 and result['admitted'] == 1
    unknown = runner.read(tmp_path/'cases/case0/candidate_0001/review/decision.json')
    assert unknown['full_test_review']['status'] == 'semantic_supported' and unknown['status'] == 'unknown'
    def one_run(candidate, source, corpus, directory, protocol):
        assert len(calls) == 3
        native.append(candidate['id'])
        outcome = dict(transport=dict(status='matched'), native=dict(controls=dict(status='all_source_controls_passed'), controlled_failure=True))
        runner.write(directory/'outcome.json', outcome)
        return outcome
    monkeypatch.setattr(runner, 'one_run', one_run)
    assert runner.run(args)['detector_alerts'] == 1
    assert native == ['case12', 'case12']
    summary = runner.read(tmp_path/'summary.json')
    assert len(summary['results']) == 2 and summary['results'][0]['alert'] is None
    assert runner.review_all(args) == result and len(calls) == 3
