from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from anchor_retrieval.syntax import Source
from relational_gap.frontend import extract_frontend, to_emitter_corpus
from scripts import run_contract_gap_generation_search as runner


CODE = 'from api import double\ndef test_value():\n    assert double(3) == 6\n'
API = 'def double(value):\n    """Return twice the input value."""\n    return value*2\n'


def prepared(tmp_path):
    repository = tmp_path/'repository'; repository.mkdir()
    (repository/'test_value.py').write_text(CODE); (repository/'api.py').write_text(API)
    cases = []
    for index in range(17):
        source = tmp_path/'sources'/str(index)
        sources = ([Source('test_value.py', CODE, 'python', 'repository'),
                    Source('api.py', API, 'python', 'repository'),
                    Source('test_history.py', 'def test_history():\n    assert PRIVATE_HISTORY\n', 'python', 'trajectory')]
                   if index == 0 else [Source('empty.py','x = 1\n','python','repository')])
        frontend = extract_frontend(sources); corpus = to_emitter_corpus(frontend)
        runner.write(source/'corpus.json',corpus); runner.write(source/'frontend.json',frontend)
        runner.write(source/'case.json',dict(repository=str(repository))); runner.write(source/'selection.json',{})
        (source/'issue.md').write_text('The double function returns twice the input value.')
        cases.append(dict(case=f'trial{index:02d}',source=str(source)))
    cohort = tmp_path/'cohort'
    runner.write(cohort/'prepared.json',dict(cases=cases,algorithm=dict(OLD_NOT_EXECUTED={})))
    runner.write(cohort/'seal.json',runner.frozen(cohort/'prepared.json'))
    args = SimpleNamespace(source_cohort=cohort, output=tmp_path/'experiment',
        deadline_utc=(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat())
    result = runner.prepare(args)
    assert result['trials'] == 17 and result['requests'] == 1
    return SimpleNamespace(input=args.output), runner.read(args.output/'prepared.json')


def generation_answer(request, *, escape_first=True):
    original = json.loads(request['prompt'])['seeds'][0]['context']['original_test']
    tests = []
    if escape_first:
        tests.append(dict(seed_alias='S1',rewritten_test=original+'\ndef test_extra():\n    assert False'))
    tests.extend(dict(seed_alias='S1', rewritten_test=original.replace('double(3) == 6', replacement))
                 for replacement in ('double(4) == 8','double(5) == 10'))
    return json.dumps(dict(tests=tests))


def provider(calls, *, generation_finish='stop', generation_content=None, reject_first_review=False):
    def dispatch(request, output, *, root):
        kind = 'generation' if request['kind'] == runner.relation.VERSION else 'review'
        calls.append(dict(kind=kind, request=request))
        if kind == 'generation':
            content = generation_content if generation_content is not None else generation_answer(request)
            finish = generation_finish
        else:
            judgment = 'unsupported' if reject_first_review and sum(c['kind']=='review' for c in calls) == 1 else 'supported'
            content = json.dumps(dict(basis='The public contract supports the fixed inputs and checks.',
                judgments={key:judgment for key in request['check_ids']}))
            finish = 'stop'
        output.mkdir()
        runner.write(output/'request.json', dict(messages=[dict(role='system',content=request['system']),
            dict(role='user',content=request['prompt'])],max_tokens=request['max_tokens'],
            thinking=dict(type=request['thinking']),reasoning_effort=request['reasoning_effort'],model='test-model'))
        raw = dict(model='test-model',usage=dict(total_tokens=100),choices=[dict(message=dict(content=content),finish_reason=finish)])
        body = json.dumps(raw).encode(); (output/'response.body').write_bytes(body)
        runner.write(output/'response.json',raw); (output/'completion.txt').write_text(content)
        runner.write(output/'manifest.json',dict(status='complete',external_model_calls=1,
            request_id=request['id'],request_sha256=runner.admission.digest(output/'request.json'),
            response_sha256=hashlib.sha256(body).hexdigest(),model='test-model',response_model='test-model',
            finish_reason=finish,usage=dict(total_tokens=100)))
    return dispatch


def native_args(args):
    return SimpleNamespace(input=args.input/'native')


def test_prepare_has_separate_fixed_budgets_and_only_original_source_context(tmp_path):
    args, protocol = prepared(tmp_path)
    assert protocol['phase'] == 'generation'
    assert protocol['generation_policy']['max_calls'] == 17
    assert protocol['generation_policy']['max_total_tokens'] == 1000000
    assert protocol['semantic_policy']['max_calls'] == 51
    assert protocol['semantic_policy']['max_total_tokens'] == 1500000
    case = protocol['cases'][0]
    request = runner.read(case['generation_request']['path'])
    assert request['thinking'] == 'enabled' and request['reasoning_effort'] == 'high'
    assert request['max_tokens'] == 16384 and request['prompt_bytes'] <= 96000
    assert 'PRIVATE_HISTORY' not in request['prompt'] and 'test_history.py' not in request['prompt']
    assert protocol['algorithm_entrypoints']['driver'] == runner.frozen(runner.__file__)
    assert not list(args.input.rglob('dispatch_claim.json'))
    assert not list(args.input.rglob('native_outcome.json'))
    assert any('extra original control tests' in line for line in protocol['comparative_limits'])


def test_generation_retains_body_escape_refusal_and_exact_proposal_ranks_before_fresh_review(tmp_path, monkeypatch):
    args, _ = prepared(tmp_path); calls = []
    monkeypatch.setattr(runner,'dispatch',provider(calls))
    generated = runner.generate(args)
    assert generated['candidates'] == 2 and generated['generation_model_calls'] == 1
    assert [call['kind'] for call in calls] == ['generation']
    decoded = runner.read(args.input/'cases/trial00/generation/decoded.json')
    assert decoded['rejected'][0]['response_index'] == 1
    assert decoded['rejected'][0]['reason'] == 'replacement_escapes_original_test'
    assert [candidate['order'] for candidate in decoded['candidates']] == [[2],[3]]
    assert 'test_extra' in (args.input/'cases/trial00/generation/completion/completion.txt').read_text()
    protocol = runner.read(args.input/'native/prepared.json')
    assert [entry['rank'] for entry in protocol['cases'][0]['candidates']] == [2,3]
    for entry in protocol['cases'][0]['candidates']:
        request = runner.read(entry['request']['path'])
        assert request['kind'] == runner.review.VERSION
        payload = json.loads(request['prompt'])
        assert payload['original_test'].endswith('assert double(3) == 6')
        assert 'replacement_escapes_original_test' not in request['prompt']
        assert 'generation_model_calls' not in request['prompt']
    assert runner.generate(args) == generated and len(calls) == 1
    assert runner.review_all(native_args(args))['admitted'] == 2
    assert [call['kind'] for call in calls] == ['generation','review','review']
    assert runner.review_all(native_args(args))['admitted'] == 2 and len(calls) == 3


def test_first_supported_native_failure_stops_even_when_repeat_does_not_confirm(tmp_path, monkeypatch):
    args, _ = prepared(tmp_path); calls = []; native = []
    monkeypatch.setattr(runner,'dispatch',provider(calls))
    runner.generate(args); runner.review_all(native_args(args))
    def execute(candidate, source, corpus, target, protocol):
        assert len(calls) == 3
        native.append(candidate['order'][0])
        outcome = dict(transport=dict(status='matched'),native=dict(
            controls=dict(status='all_source_controls_passed'),controlled_failure=len(native)==1))
        runner.write(target/'native_outcome.json',dict(unit_fixture_only=True))
        runner.write(target/'outcome.json',outcome)
        return outcome
    monkeypatch.setattr(runner,'one_run',execute)
    summary = runner.run(native_args(args))
    assert native == [2,2] and summary['detector_alerts'] == 0
    assert summary['generation_model_calls'] == 1 and summary['semantic_review_model_calls'] == 2
    assert summary['external_model_calls'] == 3 and summary['native_executions'] == 2
    assert runner.run(native_args(args))['detector_alerts'] == 0 and native == [2,2]


def test_semantic_rejection_never_executes_and_next_supported_proposal_keeps_rank(tmp_path, monkeypatch):
    args, _ = prepared(tmp_path); calls=[]; native=[]
    monkeypatch.setattr(runner,'dispatch',provider(calls,reject_first_review=True))
    runner.generate(args)
    assert runner.review_all(native_args(args))['admitted'] == 1
    def execute(candidate, source, corpus, target, protocol):
        native.append(candidate['order'][0])
        outcome=dict(transport=dict(status='matched'),native=dict(
            controls=dict(status='all_source_controls_passed'),controlled_failure=True))
        runner.write(target/'outcome.json',outcome)
        return outcome
    monkeypatch.setattr(runner,'one_run',execute)
    assert runner.run(native_args(args))['detector_alerts'] == 1
    assert native == [3,3]


@pytest.mark.parametrize('kind',['length','invalid_schema','interrupted'])
def test_generation_unknowns_never_retry_or_create_native_programs(tmp_path, monkeypatch, kind):
    args, protocol = prepared(tmp_path); calls=[]
    if kind == 'interrupted':
        case=protocol['cases'][0];request=runner.read(case['generation_request']['path'])
        runner.write(args.input/'cases/trial00/generation/dispatch_claim.json',dict(
            request=case['generation_request'],reserved_calls=1,reserved_tokens=runner._reservation(request)))
    monkeypatch.setattr(runner,'dispatch',provider(calls,
        generation_finish='length' if kind=='length' else 'stop',
        generation_content='{"tests":[],"basis":"not allowed"}' if kind=='invalid_schema' else None))
    result=runner.generate(args)
    assert result['candidates']==0 and len(calls)==(0 if kind=='interrupted' else 1)
    assert runner.generate(args)==result and len(calls)==(0 if kind=='interrupted' else 1)
    summary=runner.read(args.input/'generation_summary.json')
    assert summary['reserved_calls']==(1 if kind=='interrupted' else 0)
    assert summary['results'][0]['status']=='unknown'


def test_generation_request_identity_mismatch_refuses_dispatch(tmp_path, monkeypatch):
    args, protocol = prepared(tmp_path); calls=[]
    monkeypatch.setattr(runner,'dispatch',provider(calls))
    request_path=Path(protocol['cases'][0]['generation_request']['path'])
    request=runner.read(request_path);request['prompt']+=' altered'
    request_path.write_text(json.dumps(request))
    with pytest.raises(ValueError):runner.generate(args)
    assert calls==[]


def test_native_requires_complete_generation_and_fresh_semantic_receipts(tmp_path, monkeypatch):
    args,_=prepared(tmp_path);calls=[]
    monkeypatch.setattr(runner,'dispatch',provider(calls))
    runner.generate(args)
    with pytest.raises(FileNotFoundError):runner.run(native_args(args))
    runner.review_all(native_args(args))
    (args.input/'generation_summary_seal.json').unlink()
    monkeypatch.setattr(runner,'one_run',lambda *a,**k:pytest.fail('Missing generation receipt authorized native'))
    with pytest.raises(FileNotFoundError):runner.run(native_args(args))


def test_changed_generated_body_cannot_be_reviewed_as_the_original_model_proposal(tmp_path, monkeypatch):
    args,_=prepared(tmp_path);calls=[]
    monkeypatch.setattr(runner,'dispatch',provider(calls));runner.generate(args)
    protocol=runner.read(args.input/'native/prepared.json')
    path=Path(protocol['cases'][0]['candidates'][0]['program']['path'])
    program=runner.read(path);program['edits'][0]['after']='assert False'
    path.write_text(json.dumps(program))
    with pytest.raises(ValueError):runner.review_all(native_args(args))
    assert len(calls)==1


def test_native_protocol_cannot_replace_generation_request_receipt(tmp_path, monkeypatch):
    args,_=prepared(tmp_path);calls=[]
    monkeypatch.setattr(runner,'dispatch',provider(calls));runner.generate(args)
    protocol=runner.read(args.input/'native/prepared.json')
    original=protocol['cases'][0]['generation_request']
    copy=args.input/'request_copy.json'
    copy.write_bytes(Path(original['path']).read_bytes())
    protocol['cases'][0]['generation_request']=runner.frozen(copy)
    with pytest.raises(ValueError,match='generation receipt differs'):
        runner._verify_generation_origin(protocol)
    assert len(calls)==1


def transport_fixture(tmp_path, *, changed):
    code='def test_value():\n    assert parse("\\x1b[?25l") == "hidden"\n'
    frontend=extract_frontend([Source('test_value.py',code,'python','repository')])
    corpus=to_emitter_corpus(frontend);identifier=next(iter(corpus['tests']))
    candidate=dict(id='generated',base_test_id=identifier,source_test_ids=[identifier],imports=[],edits=[])
    actual=code.replace('test_value','test_generated')
    if changed:actual=actual.replace('[?25l','[?25h')
    emitted=tmp_path/'emitted.py';emitted.write_text(actual)
    artifact=tmp_path/'artifact'
    runner.write(artifact.parent/'accepted.json',[candidate])
    runner.write(artifact/'manifest.json',dict(obligations=[dict(candidate_id='generated',
        path='test_value.py',test_name='test_generated')],mounts=[dict(target='staged.py',
        source=str(emitted),sha256=hashlib.sha256(emitted.read_bytes()).hexdigest())]))
    runner.write(artifact/'phase_plan.json',dict(phases=[dict(role='generated',files=[dict(
        target='test_value.py',staged='staged.py')])]))
    return corpus,candidate,artifact


def test_changed_text_next_to_python_escape_is_blocked_before_native(tmp_path, monkeypatch):
    corpus,candidate,artifact=transport_fixture(tmp_path,changed=True)
    # The legacy tree-sitter shape loses plain text adjacent to escape children.
    assert runner.verify_emission(corpus,candidate,artifact)['status']=='matched'
    monkeypatch.setattr(runner,'try_emit',lambda *a:(artifact,None))
    monkeypatch.setattr(runner,'execute',lambda *a:pytest.fail('Wrong primary reached native'))
    result=runner.one_run(candidate,tmp_path,corpus,tmp_path/'run',{})
    assert result['native'] is None
    assert result['transport']['reason']=='complete_python_values_or_test_changed'


def test_exact_python_escape_values_execute_only_once(tmp_path, monkeypatch):
    corpus,candidate,artifact=transport_fixture(tmp_path,changed=False);calls=[]
    monkeypatch.setattr(runner,'try_emit',lambda *a:(artifact,None))
    monkeypatch.setattr(runner,'execute',lambda *a:calls.append('native') or dict(unit_fixture=True))
    result=runner.one_run(candidate,tmp_path,corpus,tmp_path/'run',{})
    assert calls==['native'] and result['native']==dict(unit_fixture=True)
    assert result['transport']['strict_python_transport']==runner.csi_repair_transport.VERSION


@pytest.mark.parametrize('language',['go','typescript'])
def test_non_python_keeps_existing_transport_and_single_execution(tmp_path,monkeypatch,language):
    calls=[]
    monkeypatch.setattr(runner,'try_emit',lambda *a:(tmp_path/'artifact',None))
    monkeypatch.setattr(runner.csi_repair_transport,'verify',lambda *a:pytest.fail('Python transport on other language'))
    monkeypatch.setattr(runner,'verify_emission',lambda *a:calls.append('transport') or dict(status='matched'))
    monkeypatch.setattr(runner,'execute',lambda *a:calls.append('native') or dict(unit_fixture=True))
    runner.one_run({},tmp_path,dict(language=language),tmp_path/'run',{})
    assert calls==['transport','native']
