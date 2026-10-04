from datetime import datetime, timedelta, timezone
import hashlib
import json
from types import SimpleNamespace

import pytest

from anchor_retrieval.syntax import Source
from relational_gap.frontend import extract_frontend, to_emitter_corpus
from relation_search import oracle
from relation_search.candidate_edit_transport import verify_emission
from relation_search.checkpoint import read
from scripts import run_unicode_line_field_search as runner


CODE = '''from api import consume
def test_text():
    consume({"message": "α"})
    consume({"message": "β"})
    consume({"message": "γ"})
    assert True
'''


def prepared(tmp_path):
    repository = tmp_path/'repository'; repository.mkdir()
    (repository/'test_text.py').write_text(CODE)
    cases = []
    for index in range(17):
        source = tmp_path/'sources'/str(index)
        sources = ([Source('test_text.py', CODE, 'python', 'repository'),
                    Source('test_history.py', CODE.replace('test_text', 'test_history'), 'python', 'trajectory')]
                   if index == 0 else [Source('empty.py', 'x = 1\n', 'python', 'repository')])
        frontend = extract_frontend(sources); corpus = to_emitter_corpus(frontend)
        runner.write(source/'corpus.json', corpus); runner.write(source/'frontend.json', frontend)
        runner.write(source/'case.json', dict(repository=str(repository)))
        runner.write(source/'selection.json', {})
        (source/'issue.md').write_text('The message field contains user text.')
        cases.append(dict(case=f'trial{index:02d}', source=str(source)))
    cohort = tmp_path/'cohort'
    runner.write(cohort/'prepared.json', dict(cases=cases, algorithm={'OLD_NOT_EXECUTED': {}}))
    runner.write(cohort/'seal.json', runner.frozen(cohort/'prepared.json'))
    args = SimpleNamespace(source_cohort=cohort, output=tmp_path/'prepared',
        deadline_utc=(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat())
    result = runner.collect(args, freeze=True)
    assert result['trials'] == 17 and result['selected'] == 3
    return SimpleNamespace(input=args.output), read(args.output/'prepared.json')


def test_private_harness_binding_and_prepare_seals_actual_modules(tmp_path):
    original = runner.harness.VERSION, runner.harness.relation, runner.harness.review
    engine = runner._engine()
    assert engine['collect'].__globals__ is engine
    assert engine['_verified_semantic'].__globals__ is engine
    assert engine['_native_once'].__globals__ is engine
    args, protocol = prepared(tmp_path)
    assert original == (runner.harness.VERSION, runner.harness.relation, runner.harness.review)
    assert protocol['algorithm_entrypoints']['native_adapter'] == runner.frozen(runner.__file__)
    paths = {row['path'] for row in protocol['algorithm'].values()}
    for module in [runner, runner.harness, runner.relation, runner.relation.source_fields,
                   runner.review, runner.csi_repair_transport]:
        assert str(__import__('pathlib').Path(module.__file__).resolve()) in paths
    assert protocol['semantic_policy']['max_calls'] == 64
    assert protocol['semantic_policy']['max_total_tokens'] == 1000000
    case = protocol['cases'][0]
    for entry in case['candidates']:
        request = read(entry['request']['path'])
        assert request['thinking'] == 'enabled' and request['reasoning_effort'] == 'high'
        assert request['max_tokens'] == 16384 and request['prompt_bytes'] <= 96000
        assert 'test_history.py' not in request['prompt']
    assert not list(args.input.rglob('dispatch_claim.json'))


def fake_provider(calls):
    def dispatch(request, output, *, root):
        calls.append(request)
        status = 'unknown' if len(calls) == 1 else 'supported'
        content = json.dumps(dict(basis='Fixture public contract judgment.',
            judgments={key: status for key in request['check_ids']}))
        output.mkdir()
        runner.write(output/'request.json', dict(messages=[dict(role='system', content=request['system']),
            dict(role='user', content=request['prompt'])], max_tokens=request['max_tokens'],
            thinking=dict(type=request['thinking']), reasoning_effort=request['reasoning_effort'], model='test-model'))
        raw = dict(model='test-model', usage=dict(total_tokens=100),
            choices=[dict(message=dict(content=content), finish_reason='stop')])
        body = json.dumps(raw).encode(); (output/'response.body').write_bytes(body)
        runner.write(output/'response.json', raw); (output/'completion.txt').write_text(content)
        runner.write(output/'manifest.json', dict(status='complete', external_model_calls=1,
            request_id=request['id'], request_sha256=runner.admission.digest(output/'request.json'),
            response_sha256=hashlib.sha256(body).hexdigest(), model='test-model', response_model='test-model',
            finish_reason='stop', usage=dict(total_tokens=100)))
    return dispatch


def test_fresh_reviews_unknown_abstention_and_first_failure_repeat_stop(tmp_path, monkeypatch):
    args, protocol = prepared(tmp_path)
    calls, native = [], []
    monkeypatch.setattr(runner, 'dispatch', fake_provider(calls))
    summary = runner.review_all(args)
    assert len(calls) == 3 and summary['admitted'] == 2 and summary['measured_tokens'] == 300
    def execute(candidate, source, corpus, directory, protocol):
        assert len(calls) == 3
        native.append(candidate['id'])
        outcome = dict(transport=dict(status='matched'), native=dict(
            controls=dict(status='all_source_controls_passed'), controlled_failure=len(native) == 1))
        runner.write(directory/'outcome.json', outcome)
        return outcome
    monkeypatch.setattr(runner, 'one_run', execute)
    assert runner.run(args)['detector_alerts'] == 0
    expected = read(protocol['cases'][0]['candidates'][1]['program']['path'])['id']
    assert native == [expected, expected]
    assert runner.review_all(args) == summary and len(calls) == 3


def artifact(tmp_path, candidate, code):
    output = tmp_path/'emission'; output.mkdir()
    source = output/'emitted.py'; source.write_text(code)
    runner.write(tmp_path/'accepted.json', [candidate])
    runner.write(output/'manifest.json', dict(
        obligations=[dict(candidate_id=candidate['id'], path='test_text.py', test_name='test_text')],
        mounts=[dict(source=str(source), target='stage.py', sha256=hashlib.sha256(source.read_bytes()).hexdigest())]))
    runner.write(output/'phase_plan.json', dict(phases=[dict(role='generated',
        files=[dict(target='test_text.py', staged='stage.py')])]))
    return output


def test_strict_transport_rejects_text_change_around_escape_before_execution(tmp_path, monkeypatch):
    frontend = extract_frontend([Source('test_text.py', CODE, 'python', 'repository')])
    corpus = to_emitter_corpus(frontend)
    candidate = runner.relation.generate(corpus, frontend, 'message')['candidates'][0]
    intended = oracle.preview(corpus, candidate)
    wrong = intended.replace('α\\u2028', 'wrong\\u2028')
    assert wrong != intended
    emitted = artifact(tmp_path, candidate, wrong)
    assert verify_emission(corpus, candidate, emitted)['status'] == 'matched'
    monkeypatch.setattr(runner, 'try_emit', lambda *a: (emitted, None))
    monkeypatch.setattr(runner, 'execute', lambda *a: pytest.fail('Altered string reached subject'))
    outcome = runner.one_run(candidate, tmp_path, corpus, tmp_path/'run', {})
    assert outcome['transport']['reason'] == 'complete_python_values_or_test_changed'
    assert outcome['native'] is None


def test_exact_complete_transport_executes_adapter_once(tmp_path, monkeypatch):
    frontend = extract_frontend([Source('test_text.py', CODE, 'python', 'repository')])
    corpus = to_emitter_corpus(frontend)
    candidate = runner.relation.generate(corpus, frontend, 'message')['candidates'][0]
    emitted = artifact(tmp_path, candidate, oracle.preview(corpus, candidate))
    monkeypatch.setattr(runner, 'try_emit', lambda *a: (emitted, None))
    calls = []
    monkeypatch.setattr(runner, 'execute', lambda *a: calls.append(a) or dict(fixture_only=True))
    outcome = runner.one_run(candidate, tmp_path, corpus, tmp_path/'run', {})
    assert len(calls) == 1 and outcome['transport']['status'] == 'matched'
