"""No provider calls in these scheduler tests; fake receipts exercise resumption."""
from datetime import timedelta
import json
from types import SimpleNamespace

from relation_search import observed_precondition_discovery as discovery
from scripts import discover_observed_preconditions as runner
from relational_gap.provider import encoded


def prepared(tmp_path, *, count=2, max_calls=1):
    issue = 'Observe returns a ready value. Await must succeed without changing state.'
    code = ('package sample\ntype Box struct{}\nfunc(b *Box) Observe()(int,error){return 1,nil}\n'
            'func(b *Box) Await(v int)error{return nil}\n')
    corpus = dict(language='go', sources={'api.go': dict(code=code, language='go', origin='repository')})
    source = tmp_path/'source'; source.mkdir()
    runner.write(source/'corpus.json', corpus); (source/'issue.md').write_text(issue)
    cohort = tmp_path/'cohort.json'; runner.write(cohort, {})
    cases = []
    for index in range(count):
        case = 'trial_'+str(index); folder = tmp_path/'cases'/case
        result = discovery.prepare(corpus, issue)
        runner.write(folder/'catalog.json', result['catalog'])
        runner.write(folder/'request.json', result['request'])
        runner.write(folder/'analysis.json', dict(status=result['status']))
        cases.append(dict(case=case, source=str(source),
            source_inputs={name:runner.frozen(source/name) for name in ('corpus.json','issue.md')},
            catalog=runner.frozen(folder/'catalog.json'), analysis=runner.frozen(folder/'analysis.json'),
            request=runner.frozen(folder/'request.json'), status=result['status']))
    policy = dict(max_calls=max_calls, max_total_tokens=500000,
                  deadline_utc=(runner.now()+timedelta(hours=1)).isoformat(), minimum_dispatch_seconds=300)
    runner.write(tmp_path/'prepared.json', dict(version=runner.VERSION, cases=cases, denominator=count,
        policy=policy, algorithm={}, source_cohort=runner.frozen(cohort)))
    runner.write(tmp_path/'seal.json', runner.frozen(tmp_path/'prepared.json'))
    return SimpleNamespace(input=tmp_path), cases


def fake_provider(calls):
    def dispatch(request, output, *, root):
        calls.append(request['id']); output.mkdir()
        wire = dict(messages=[dict(role='system', content=request['system']),
                              dict(role='user', content=request['prompt'])])
        (output/'request.json').write_bytes(encoded(wire))
        runner.write(output/'manifest.json', dict(status='complete', external_model_calls=1,
            request_id=request['id'], request_sha256=runner.digest(output/'request.json'),
            finish_reason='stop', usage=dict(total_tokens=120)))
        (output/'completion.txt').write_text('{"relations":[]}')
    return dispatch


def test_uniform_call_budget_keeps_all_trials_and_resume_does_not_dispatch(tmp_path, monkeypatch):
    args, _ = prepared(tmp_path)
    calls = []; monkeypatch.setattr(runner, 'dispatch', fake_provider(calls))
    result = runner.run(args)
    assert result['denominator'] == 2 and result['provider_calls'] == 1
    assert result['measured_tokens'] == 120 and result['reserved_tokens'] == 0
    assert len(calls) == 1
    summary = runner.read(tmp_path/'summary.json')
    assert summary['results'][1]['status'] == 'unknown'
    assert len(list((tmp_path/'relations').glob('*.json'))) == 2
    assert runner.run(args) == result and len(calls) == 1


def test_claim_without_receipt_is_reserved_and_never_reissued(tmp_path, monkeypatch):
    args, cases = prepared(tmp_path, count=1)
    entry = cases[0]; request = runner.read(entry['request']['path'])
    runner.write(tmp_path/'cases'/entry['case']/'dispatch_claim.json', dict(request=entry['request'],
        reserved_tokens=runner._reservation(request), reserved_calls=1, created_utc=runner.now().isoformat()))
    calls = []; monkeypatch.setattr(runner, 'dispatch', fake_provider(calls))
    result = runner.run(args)
    assert not calls and result['provider_calls'] == 0 and result['reserved_calls'] == 1
    assert result['reserved_tokens'] == runner._reservation(request)
    assert result['selected_relations'] == 0
    assert runner.run(args) == result and not calls


def test_dispatch_exception_without_manifest_is_not_retried(tmp_path, monkeypatch):
    args, _ = prepared(tmp_path, count=1)
    calls = []
    def broken(*a, **kw):
        calls.append(1)
        raise RuntimeError('PRIVATE_ENDPOINT_DO_NOT_LOG')
    monkeypatch.setattr(runner, 'dispatch', broken)
    result = runner.run(args)
    assert len(calls) == 1 and result['reserved_calls'] == 1
    assert runner.run(args) == result and len(calls) == 1
    assert 'PRIVATE' not in (tmp_path/'cases'/'trial_0'/'decision.json').read_text()


def test_prepare_freezes_source_only_catalog_and_run_consumes_its_exact_request(tmp_path, monkeypatch):
    seed = tmp_path/'seed'; seed.mkdir()
    _, cases = prepared(seed, count=1)
    cohort = tmp_path/'cohort'; cohort.mkdir()
    runner.write(cohort/'prepared.json', dict(cases=[dict(case='generic', source=cases[0]['source'],
        evaluation_label='PRIVATE_LABEL', candidates=['PRIVATE_CANDIDATE'])]))
    runner.write(cohort/'seal.json', runner.frozen(cohort/'prepared.json'))
    args = SimpleNamespace(source_cohort=cohort, output=tmp_path/'discovery',
        max_calls=17, max_total_tokens=500000, max_prompt_bytes=96000, relations_per_trial=4,
        deadline_utc=(runner.now()+timedelta(hours=1)).isoformat())
    calls = []; monkeypatch.setattr(runner, 'dispatch', fake_provider(calls))
    result = runner.prepare(args)
    assert result['denominator'] == result['requests'] == 1 and not calls
    manifest = runner.read(args.output/'prepared.json')
    request = runner.read(manifest['cases'][0]['request']['path'])
    assert 'PRIVATE' not in request['prompt']
    assert request['id'] == discovery.request_identity(request)
    assert runner.run(SimpleNamespace(input=args.output))['provider_calls'] == 1
    assert calls == [request['id']]
