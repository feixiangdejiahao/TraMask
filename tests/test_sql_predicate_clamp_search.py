from datetime import datetime, timedelta, timezone
import hashlib
import json
from types import SimpleNamespace

import pytest

from anchor_retrieval.syntax import Source
from relational_gap.frontend import extract_frontend, to_emitter_corpus
from scripts import run_sql_predicate_clamp_search as runner

CODE = '''import pytest
def test_rule(store):
    store.register("score < 10")
    store.register("score > -1")
    assert store.count() == 0
'''


def source_cohort(tmp_path):
    repository = tmp_path/'repository'; repository.mkdir()
    (repository/'test_rule.py').write_text(CODE)
    original = Source('test_rule.py', CODE, 'python', 'repository')
    historical = Source('old_test.py', CODE.replace('test_rule', 'test_old'), 'python', 'trajectory')
    frontend = extract_frontend([original, historical]); corpus = to_emitter_corpus(frontend)
    cases = []
    for i in range(17):
        source = tmp_path/'sources'/str(i)
        front = frontend if i == 0 else extract_frontend([Source('empty.py', 'x=1\n', 'python', 'repository')])
        for name, value in [('corpus.json', corpus if i == 0 else to_emitter_corpus(front)),
                            ('frontend.json', front), ('case.json', dict(repository=str(repository))), ('selection.json', {})]:
            runner.write(source/name, value)
        (source/'issue.md').write_text('SQLite expressions validate numeric input rows.')
        cases.append(dict(case=f'trial{i:02d}', source=str(source)))
    cohort = tmp_path/'cohort'
    runner.write(cohort/'prepared.json', dict(cases=cases, old_algorithm='not an executed dependency'))
    runner.write(cohort/'seal.json', runner.harness.frozen(cohort/'prepared.json'))
    return SimpleNamespace(source_cohort=cohort, output=tmp_path/'prepared',
        deadline_utc=(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat())


def test_private_namespace_and_strict_python_transport_precede_execution(tmp_path, monkeypatch):
    old = runner.harness.VERSION, runner.harness.review, runner.harness.one_run
    engine = runner._engine()
    assert engine['collect'].__globals__ is engine
    assert engine['_verified_semantic'].__globals__ is engine
    assert engine['review'] is runner.review and engine['relation'] is runner.relation
    assert (runner.harness.VERSION, runner.harness.review, runner.harness.one_run) == old
    monkeypatch.setattr(runner, 'try_emit', lambda *a: (tmp_path/'artifact', None))
    monkeypatch.setattr(runner.csi_repair_transport, 'verify', lambda *a: dict(status='mismatch'))
    monkeypatch.setattr(runner, 'execute', lambda *a: pytest.fail('Mismatched candidate executed'))
    assert runner.one_run({}, tmp_path, {}, tmp_path/'run', {})['native'] is None


def fake_provider(calls):
    def dispatch(request, output, *, root):
        calls.append(request['id']); output.mkdir()
        answer = dict(basis='Synthetic response for gate tests.', judgments={key: 'supported' for key in request['check_ids']})
        if len(calls) == 1:
            answer['judgments']['SQL_VALUES'] = 'unknown'
        completion = json.dumps(answer)
        runner.write(output/'request.json', dict(messages=[dict(role='system', content=request['system']),
            dict(role='user', content=request['prompt'])], max_tokens=request['max_tokens'],
            thinking=dict(type=request['thinking']), reasoning_effort=request['reasoning_effort'], model='test-model'))
        raw = dict(model='test-model', usage=dict(total_tokens=100),
            choices=[dict(message=dict(content=completion), finish_reason='stop')])
        body = json.dumps(raw).encode(); (output/'response.body').write_bytes(body)
        runner.write(output/'response.json', raw)
        runner.write(output/'manifest.json', dict(status='complete', external_model_calls=1,
            request_id=request['id'], request_sha256=runner.harness.admission.digest(output/'request.json'),
            response_sha256=hashlib.sha256(body).hexdigest(), model='test-model', response_model='test-model',
            finish_reason='stop', usage=dict(total_tokens=100)))
        (output/'completion.txt').write_text(completion)
    return dispatch


def test_full_cohort_freeze_source_projection_review_gate_fixed_prefix_and_resume(tmp_path, monkeypatch):
    args = source_cohort(tmp_path)
    frozen = runner.collect(args, freeze=True)
    assert frozen['trials'] == 17 and frozen['selected'] == 2
    protocol = runner.harness.read(frozen['record']['path'])
    engine = runner._engine(); engine['_verify_algorithm'](protocol)
    assert protocol['algorithm_entrypoints']['driver'] == runner.harness.frozen(runner.__file__)
    assert protocol['algorithm_entrypoints']['native_adapter'] == runner.harness.frozen(runner.__file__)
    assert protocol['semantic_policy']['max_calls'] == 64 and protocol['external_model_calls'] == 0
    entry = protocol['cases'][0]['candidates'][0]
    request = runner.harness.read(entry['request']['path'])
    assert request['kind'] == runner.review.VERSION
    assert 'test_old' not in request['prompt'] and 'old_test.py' not in request['prompt']
    assert set(runner.review.EXTRA_CHECKS) <= set(request['check_ids'])
    assert request['id'] == runner.harness.admission._request_identity(request)
    assert not list(args.output.rglob('dispatch_claim.json'))
    calls, native = [], []
    monkeypatch.setattr(runner, 'dispatch', fake_provider(calls))
    runargs = SimpleNamespace(input=args.output)
    semantic = runner.review_all(runargs)
    assert len(calls) == 2 and semantic['admitted'] == 1
    def one_run(candidate, source, corpus, directory, protocol):
        assert len(calls) == 2
        native.append(candidate['source_evidence']['predicate']['value_before'])
        outcome = dict(transport=dict(status='matched'), native=dict(
            controls=dict(status='all_source_controls_passed'), controlled_failure=True))
        runner.write(directory/'outcome.json', outcome)
        return outcome
    monkeypatch.setattr(runner, 'one_run', one_run)
    outcome = runner.run(runargs)
    summary = runner.harness.read(args.output/'summary.json')
    assert outcome['detector_alerts'] == 1 and len(summary['results']) == 17
    assert native == ['score > -1', 'score > -1']
    assert runner.review_all(runargs) == semantic and len(calls) == 2
    assert runner.run(runargs) == summary and len(native) == 2
    # Complete result seals remain binding during resume.
    result = args.output/'cases/trial00/result.json'
    result.write_text(result.read_text()+' ')
    with pytest.raises(ValueError, match='Changed input|seal'):
        runner.run(runargs)
