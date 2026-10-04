from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from anchor_retrieval.syntax import Source
from relational_gap.frontend import extract_frontend, to_emitter_corpus
from scripts import run_contract_gap_generation_search as original
from scripts import run_planned_contract_gap_generation_search as runner


def prepared(tmp_path):
    cases = []
    for index in range(17):
        source = tmp_path/'sources'/str(index)
        repository = source/'repository'
        repository.mkdir(parents=True)
        code = 'from api import double\ndef test_value():\n    assert double(3) == 6\n' if index < 2 else 'x = 1\n'
        api = 'def double(n):\n    """Return twice n."""\n    return n*2\n'
        (repository/'test_value.py').write_text(code)
        (repository/'api.py').write_text(api)
        frontend = extract_frontend([Source('test_value.py', code, 'python', 'repository'),
            Source('api.py', api, 'python', 'repository')])
        runner.write(source/'corpus.json', to_emitter_corpus(frontend))
        runner.write(source/'frontend.json', frontend)
        runner.write(source/'case.json', dict(repository=str(repository)))
        runner.write(source/'selection.json', {})
        (source/'issue.md').write_text('double returns twice its input.')
        cases.append(dict(case=f'trial{index:02d}', source=str(source)))
    cohort = tmp_path/'cohort'
    runner.write(cohort/'prepared.json', dict(cases=cases))
    runner.write(cohort/'seal.json', runner.frozen(cohort/'prepared.json'))
    deadline = (datetime.now(timezone.utc)+timedelta(hours=1)).isoformat()
    inherited = tmp_path/'r18'
    original.prepare(SimpleNamespace(source_cohort=cohort, output=inherited, deadline_utc=deadline))
    (inherited/'cases/trial00/generation/decoded.json').write_text('FORBIDDEN_OLD_GENERATED_DATA_NOT_JSON')
    target = tmp_path/'r27'
    result = runner.prepare(SimpleNamespace(source_cohort=inherited, output=target, deadline_utc=deadline))
    assert result['trials'] == 17 and result['requests'] == 2
    return SimpleNamespace(input=target), runner.read(target/'prepared.json')


def provider(calls, fault=None):
    def dispatch(request, output, *, root):
        payload = json.loads(request['prompt'])
        stage = 'planning' if request['kind'] == runner.planning.VERSION else 'generation' if 'seeds' in payload else 'review'
        calls.append(stage)
        finish = 'stop'
        if stage == 'planning':
            content = json.dumps({'ids': [payload['declarations'][0]['id']]})
            if fault == 'length':
                finish = 'length'
            elif fault == 'format':
                content = '{"ids":'
            elif fault == 'empty':
                content = '{"ids":[]}'
        elif stage == 'generation':
            seed = payload['seeds'][0]
            code = seed['context']['original_test'].replace('double(3) == 6', 'double(4) == 8')
            content = json.dumps({'tests': [dict(seed_alias=seed['seed_alias'], rewritten_test=code)]})
        else:
            content = json.dumps(dict(basis='fixture public contract', judgments={k: 'supported' for k in request['check_ids']}))
        output.mkdir()
        runner.write(output/'request.json', dict(messages=[dict(role='system', content=request['system']),
            dict(role='user', content=request['prompt'])], max_tokens=request['max_tokens'],
            thinking=dict(type=request['thinking']), reasoning_effort=request['reasoning_effort'], model='fixture'))
        raw = dict(model='fixture', usage=dict(total_tokens=100),
            choices=[dict(message=dict(content=content), finish_reason=finish)])
        body = json.dumps(raw).encode()
        (output/'response.body').write_bytes(body)
        runner.write(output/'response.json', raw)
        (output/'completion.txt').write_text(content)
        runner.write(output/'manifest.json', dict(status='complete', external_model_calls=1,
            request_id=request['id'], request_sha256=original.admission.digest(output/'request.json'),
            response_sha256=hashlib.sha256(body).hexdigest(), model='fixture', response_model='fixture',
            finish_reason=finish, usage=dict(total_tokens=100)))
    return dispatch


def generation(args):
    return SimpleNamespace(input=args.input/'generation')


def native(args):
    return SimpleNamespace(input=args.input/'generation/native')


def prepare_generation(args):
    return runner.prepare_generation(SimpleNamespace(input=args.input, output=args.input/'generation'))


def test_stage_boundary_raw_origin_and_full_fresh_review(tmp_path, monkeypatch):
    before = (original.VERSION, original.relation, original.dispatch)
    args, protocol = prepared(tmp_path)
    calls = []
    monkeypatch.setattr(runner, 'dispatch', provider(calls))
    summary = runner.plan(args)
    assert calls == ['planning', 'planning'] and summary['measured_tokens'] == 200
    assert len(summary['results']) == 17 and not (args.input/'generation').exists()
    assert runner.plan(args) == summary and len(calls) == 2
    result = prepare_generation(args)
    assert result['requests'] == 2 and result['planning_costs']['provider_calls'] == 2
    assert len(calls) == 2  # freezing generation never dispatches
    generated = runner.generate(generation(args))
    assert generated['candidates'] == 2 and calls == ['planning', 'planning', 'generation', 'generation']
    expanded = runner.read(native(args).input/'prepared.json')
    assert expanded['planning_costs']['measured_tokens'] == 200
    for case in expanded['cases'][:2]:
        candidate = runner.read(case['candidates'][0]['program']['path'])
        assert candidate['source_provenance']['source_file']['origin'] == 'repository'
        request = runner.read(case['candidates'][0]['request']['path'])
        assert 'FORBIDDEN_OLD_GENERATED_DATA' not in request['prompt']
        payload = json.loads(request['prompt'])
        assert 'double(4) == 8' in payload['modified_test'] and 'double(3) == 6' in payload['original_test']
    assert runner.review_all(native(args))['admitted'] == 2
    assert calls[-2:] == ['review', 'review']
    assert before == (original.VERSION, original.relation, original.dispatch)


@pytest.mark.parametrize('fault', ['length', 'format', 'empty'])
def test_failed_planning_falls_back_but_costs_are_preserved(tmp_path, monkeypatch, fault):
    args, protocol = prepared(tmp_path)
    calls = []
    monkeypatch.setattr(runner, 'dispatch', provider(calls, fault))
    summary = runner.plan(args)
    prepare_generation(args)
    planned = runner.read(generation(args).input/'prepared.json')
    for old, case in zip(protocol['cases'], planned['cases']):
        result = runner.read(case['generation']['path'])
        inherited = runner.read(old['inherited_case']['generation']['path'])
        assert result['request'] == inherited['request']
        assert result['planning_context']['status'] == 'fallback'
    assert summary['provider_calls'] == 2 and planned['planning_costs']['measured_tokens'] == 200


def test_interrupted_planning_is_reserved_unknown_and_never_retried(tmp_path, monkeypatch):
    args, protocol = prepared(tmp_path)
    first = protocol['cases'][0]
    request = runner.read(first['request']['path'])
    runner.write(args.input/'cases/trial00/planning/dispatch_claim.json', dict(request=first['request'],
        reserved_calls=1, reserved_tokens=runner._reservation(request)))
    calls = []
    monkeypatch.setattr(runner, 'dispatch', provider(calls))
    summary = runner.plan(args)
    assert calls == ['planning'] and summary['provider_calls'] == 1 and summary['reserved_calls'] == 1
    assert summary['usage_missing'] == 1
    runner.plan(args)
    assert calls == ['planning']
    prepare_generation(args)
    result = runner.read(generation(args).input/'cases/trial00/generation/preparation.json')
    assert result['planning_context']['status'] == 'fallback'


def test_budget_withholding_keeps_all17_and_fallback_without_dispatch(tmp_path, monkeypatch):
    args, _ = prepared(tmp_path)
    calls = []
    monkeypatch.setattr(runner, 'dispatch', provider(calls))
    monkeypatch.setattr(runner, '_reservation', lambda request: 500001)
    summary = runner.plan(args)
    assert calls == [] and len(summary['results']) == 17
    assert [row['dispatch_withheld_reason'] for row in summary['results'][:2]] == ['planning_budget']*2
    prepare_generation(args)


def test_tampered_raw_selection_blocks_generation_preparation(tmp_path, monkeypatch):
    args, _ = prepared(tmp_path)
    monkeypatch.setattr(runner, 'dispatch', provider([]))
    runner.plan(args)
    path = args.input/'cases/trial00/planning/completion/completion.txt'
    path.write_text('{"ids":[]}')
    with pytest.raises(ValueError):
        prepare_generation(args)


def test_native_first_failure_repeat_retains_separate_planning_accounting(tmp_path, monkeypatch):
    args, _ = prepared(tmp_path)
    calls, runs = [], []
    monkeypatch.setattr(runner, 'dispatch', provider(calls))
    runner.plan(args)
    prepare_generation(args)
    runner.generate(generation(args))
    runner.review_all(native(args))
    def execute(candidate, source, corpus, target, protocol):
        runs.append((Path(source).name, candidate['order'][0]))
        outcome = dict(transport=dict(status='matched'),
            native=dict(controls=dict(status='all_source_controls_passed'), controlled_failure=True))
        runner.write(target/'native_outcome.json', dict(fixture=True))
        runner.write(target/'outcome.json', outcome)
        return outcome
    monkeypatch.setattr(runner, 'one_run', execute)
    result = runner.run(native(args))
    assert runs == [('0', 1), ('0', 1), ('1', 1), ('1', 1)]
    assert result['planning_model_calls'] == result['generation_model_calls'] == result['semantic_review_model_calls'] == 2
    assert result['planning_measured_tokens'] == 200
    assert runner.run(native(args)) == result and len(runs) == 4
