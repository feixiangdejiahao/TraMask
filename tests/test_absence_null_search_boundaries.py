"""Source role separation and immutable recovery, without real dispatch/run."""
from datetime import datetime, timedelta, timezone
import hashlib
import json
from types import SimpleNamespace

import pytest

from anchor_retrieval.syntax import Source
from generic_composition.emitter import emit
from relational_gap.frontend import extract_frontend, to_emitter_corpus
from scripts import run_absence_null_search as runner


ORIGINAL = '''import pytest
from example import validate, Invalid

@pytest.mark.parametrize("payload", [{"quota": "bad"}])
def test_invalid(payload):
    with pytest.raises(Invalid):
        validate(payload)
'''
HISTORY = '''from example import validate
def test_historical_control():
    validate({"quota": "HISTORY_ONLY_SECRET_MARKER"})
    assert True
'''


def source_fixture():
    frontend = extract_frontend([
        Source('test_original.py', ORIGINAL, 'python', 'repository'),
        Source('test_history.py', HISTORY, 'python', 'trajectory'),
    ])
    corpus = to_emitter_corpus(frontend)
    for row in corpus['tests'].values():
        row['retrieval_rank'] = 4
    return corpus, frontend


def prepared(tmp_path):
    source = tmp_path/'source'
    for name in ('corpus.json', 'frontend.json', 'case.json', 'selection.json'):
        runner.write(source/name, {})
    (source/'issue.md').write_text('quota must be an integer if present.')
    inputs = {name: runner.frozen(source/name) for name in
              ('corpus.json', 'frontend.json', 'case.json', 'selection.json', 'issue.md')}
    directory = tmp_path/'cases'/'generic'
    runner.write(directory/'generation.json', dict(status='source_hypotheses'))
    candidate = directory/'candidate_0001'
    runner.write(candidate/'program.json', dict(id='candidate_1'))
    request = runner.admission._configure_request(dict(system='contract', prompt='support'),
        SimpleNamespace(thinking='enabled', output_token_limit=16384, reasoning_effort='high'))
    runner.write(candidate/'review/analysis.json', dict(status='prepared'))
    runner.write(candidate/'review/request.json', request)
    entry = dict(rank=1, program=runner.frozen(candidate/'program.json'),
        analysis=runner.frozen(candidate/'review/analysis.json'),
        request=runner.frozen(candidate/'review/request.json'))
    protocol = dict(version=runner.VERSION, algorithm={}, trial_denominator=1,
        cases=[dict(case='generic', source=str(source), inputs=inputs, source_context=None,
            generation=runner.frozen(directory/'generation.json'),
            status='source_hypotheses', candidates=[entry])],
        max_native_executions=17, timeout=180,
        semantic_policy=dict(max_calls=64, max_total_tokens=1000000),
        deadline_utc=(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat())
    runner.write(tmp_path/'prepared.json', protocol)
    runner.write(tmp_path/'seal.json', runner.frozen(tmp_path/'prepared.json'))
    return SimpleNamespace(input=tmp_path), protocol, candidate


def provider_fixture(request, output, *, root):
    """Match the artifact structure emitted by relational_gap.provider."""
    output.mkdir()
    wire = dict(model='fixture-model', temperature=0, stream=False,
        response_format=dict(type='json_object'), max_tokens=request['max_tokens'],
        thinking=dict(type=request['thinking']), reasoning_effort=request['reasoning_effort'],
        messages=[dict(role='system', content=request['system']),
                  dict(role='user', content=request['prompt'])])
    runner.write(output/'request.json', wire)
    raw = dict(model='fixture-response-model', choices=[dict(finish_reason='stop',
        message=dict(content=request['prompt']))], usage=dict(total_tokens=100))
    body = json.dumps(raw).encode()
    (output/'response.body').write_bytes(body)
    runner.write(output/'response.json', raw)
    (output/'completion.txt').write_text(request['prompt'])
    runner.write(output/'manifest.json', dict(status='complete', external_model_calls=1,
        model=wire['model'], response_model=raw['model'], request_id=request['id'],
        request_sha256=runner.admission.digest(output/'request.json'),
        response_sha256=hashlib.sha256(body).hexdigest(), finish_reason='stop', usage=raw['usage']))


def supported(*args, **kwargs):
    return dict(status='semantic_supported', alarm_eligible=True)


def native_fixture(candidate, source, corpus, target, protocol):
    outcome = dict(transport=dict(status='matched'), native=dict(
        controls=dict(status='all_source_controls_passed'), controlled_failure=True))
    runner.write(target/'outcome.json', outcome)
    return outcome


def test_repository_projection_removes_history_from_review_and_native_controls():
    corpus, frontend = source_fixture()
    candidate = runner.relation.generate(corpus, frontend, 'quota')['candidates'][0]
    projected, refreshed, manifest = runner.repository_projection(corpus, frontend)
    assert set(projected['sources']) == {'test_original.py'}
    assert manifest['excluded_source_count'] == 1
    assert manifest['source_sha256']['test_original.py'] == hashlib.sha256(ORIGINAL.encode()).hexdigest()
    assert all(row['retrieval_rank'] == 4 for row in projected['tests'].values())
    assert 'HISTORY_ONLY_SECRET_MARKER' not in json.dumps((projected, refreshed))
    review = runner.review.prepare(projected, refreshed, candidate,
        'quota is optional. If present it must be an integer.', max_prompt_bytes=96000)
    assert review['request'] is not None
    assert 'HISTORY_ONLY_SECRET_MARKER' not in review['request']['prompt']
    assert 'test_history.py' not in review['request']['prompt']
    # Native consumes the original snapshot. Exact source test IDs still select
    # only the original repository control and the edited complete test.
    emitted = emit(corpus, [candidate])
    assert not emitted['unsupported']
    assert set(emitted['files']) == {'test_original.py'}
    assert [row['base_test_id'] for row in emitted['controls']] == [candidate['base_test_id']]
    assert '@pytest.mark.parametrize' in emitted['files']['test_original.py']
    assert 'with pytest.raises(Invalid)' in emitted['files']['test_original.py']


def test_collect_projects_before_enrichment_and_records_original_input_receipts(tmp_path, monkeypatch):
    corpus, frontend = source_fixture()
    source = tmp_path/'source'
    runner.write(source/'corpus.json', corpus)
    runner.write(source/'frontend.json', frontend)
    runner.write(source/'case.json', {})
    runner.write(source/'selection.json', {})
    (source/'issue.md').write_text('quota is optional. If present it must be an integer.')
    cohort = tmp_path/'cohort'
    runner.write(cohort/'prepared.json', dict(cases=[dict(case='generic', source=str(source))]))
    runner.write(cohort/'seal.json', runner.frozen(cohort/'prepared.json'))
    calls = []
    def enrich(projected, refreshed, candidates, *args):
        assert set(projected['sources']) == {'test_original.py'}
        assert 'test_history.py' not in json.dumps(refreshed)
        calls.append(sorted(candidates))
        return projected, None
    monkeypatch.setattr(runner.admission, '_enrich', enrich)
    monkeypatch.setattr(runner.admission, '_preload_local_imports', lambda *args: None)
    monkeypatch.setattr(runner.admission, '_loaded_sources', lambda: {})
    output = tmp_path/'prepared'
    runner.collect(SimpleNamespace(source_cohort=cohort, output=output,
        deadline_utc=(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat()), freeze=True)
    assert len(calls) == 1
    case = runner.read(output/'prepared.json')['cases'][0]
    projection = runner.read(case['review_projection']['path'])
    assert projection['original_inputs'] == {key: case['inputs'][key] for key in ('corpus.json', 'frontend.json')}
    assert runner.read(case['inputs']['corpus.json']['path']) == corpus
    assert 'test_history.py' not in json.dumps(runner.read(projection['corpus']['path']))
    request = runner.read(case['candidates'][0]['request']['path'])
    assert 'HISTORY_ONLY_SECRET_MARKER' not in request['prompt']
    assert 'test_history.py' not in request['prompt']
    runner._verify_case_inputs(case)
    path = output/'cases/generic/review_projection/frontend.json'
    path.write_text(path.read_text()+' ')
    with pytest.raises(ValueError):
        runner._verify_case_inputs(case)


@pytest.mark.parametrize('artifact,partial', [
    ('result.json', True), ('result.json', False), ('summary.json', False),
    ('outcome.json', False), ('decision.json', False),
])
def test_completed_native_results_and_summary_are_verified_on_resume(tmp_path, monkeypatch, artifact, partial):
    args, _, candidate = prepared(tmp_path)
    monkeypatch.setattr(runner, 'dispatch', provider_fixture)
    monkeypatch.setattr(runner.review, 'decide', supported)
    monkeypatch.setattr(runner, 'one_run', native_fixture)
    runner.review_all(args)
    runner.run(args)
    assert runner.run(args)['detector_alerts'] == 1
    if partial:
        (tmp_path/'summary.json').unlink()
        (tmp_path/'summary_seal.json').unlink()
    path = {'result.json': candidate.parent/'result.json',
            'summary.json': tmp_path/'summary.json',
            'outcome.json': candidate/'initial/outcome.json',
            'decision.json': candidate/'review/decision.json'}[artifact]
    path.write_text(path.read_text()+' ')
    monkeypatch.setattr(runner, 'one_run', lambda *a, **k: pytest.fail('Changed completion executed'))
    with pytest.raises(ValueError):
        runner.run(args)


@pytest.mark.parametrize('artifact', [
    'completion.txt', 'response.body', 'response.json', 'missing_response',
    'manifest_usage', 'wire_prompt',
])
def test_interrupted_complete_response_must_match_raw_receipts(tmp_path, monkeypatch, artifact):
    args, protocol, candidate = prepared(tmp_path)
    entry = protocol['cases'][0]['candidates'][0]
    request = runner.read(entry['request']['path'])
    folder = candidate/'review'
    runner.write(folder/'dispatch_claim.json', dict(request=entry['request'],
        reserved_tokens=runner._reservation(request), reserved_calls=1))
    completion = folder/'completion'
    provider_fixture(request, completion, root=tmp_path)
    if artifact == 'missing_response':
        (completion/'response.body').unlink()
    elif artifact == 'manifest_usage':
        path = completion/'manifest.json'
        receipt = runner.read(path); receipt['usage'] = dict(total_tokens=0)
        path.write_text(json.dumps(receipt))
    elif artifact == 'wire_prompt':
        path = completion/'request.json'
        wire = runner.read(path); wire['messages'][1]['content'] = 'different contract'
        path.write_text(json.dumps(wire))
        manifest = completion/'manifest.json'
        receipt = runner.read(manifest); receipt['request_sha256'] = runner.admission.digest(path)
        manifest.write_text(json.dumps(receipt))
    elif artifact == 'response.json':
        path = completion/artifact
        raw = runner.read(path); raw['choices'][0]['message']['content'] = 'different answer'
        path.write_text(json.dumps(raw))
    else:
        path = completion/artifact
        path.write_text(path.read_text()+' ')
    monkeypatch.setattr(runner, 'dispatch', lambda *a, **k: pytest.fail('Dispatch repeated'))
    monkeypatch.setattr(runner.review, 'decide', lambda *a, **k: pytest.fail('Inconsistent response admitted'))
    with pytest.raises((ValueError, FileNotFoundError)):
        runner.review_all(args)
    assert not (folder/'result.json').exists()
    assert not (tmp_path/'semantic_summary.json').exists()


def test_interrupted_complete_response_resumes_once_without_another_dispatch(tmp_path, monkeypatch):
    args, protocol, candidate = prepared(tmp_path)
    entry = protocol['cases'][0]['candidates'][0]
    request = runner.read(entry['request']['path'])
    runner.write(candidate/'review/dispatch_claim.json', dict(request=entry['request'],
        reserved_tokens=runner._reservation(request), reserved_calls=1))
    provider_fixture(request, candidate/'review/completion', root=tmp_path)
    monkeypatch.setattr(runner, 'dispatch', lambda *a, **k: pytest.fail('Dispatch repeated'))
    monkeypatch.setattr(runner.review, 'decide', supported)
    summary = runner.review_all(args)
    assert summary['admitted'] == 1 and summary['provider_calls'] == 1
    assert summary['reserved_calls'] == 0 and summary['measured_tokens'] == 100
    assert runner.review_all(args) == summary
