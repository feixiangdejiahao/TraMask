import copy
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import run_direct_generation_provenance_replay as runner
import test_contract_gap_generation_search as direct_fixture
import test_atomic_contract_gap_generation_search as atomic_fixture


def original_run(tmp_path, monkeypatch, kind='direct'):
    tmp_path.mkdir(parents=True, exist_ok=True)
    fixture = direct_fixture if kind == 'direct' else atomic_fixture
    args, protocol = fixture.prepared(tmp_path)
    calls = []
    monkeypatch.setattr(fixture.runner, 'dispatch', fixture.provider(calls))
    fixture.runner.generate(args)
    fixture.runner.review_all(fixture.native_args(args))
    monkeypatch.undo()
    return args.input/'native', calls


def prepared(tmp_path, monkeypatch, kind='direct'):
    origin, calls = original_run(tmp_path/'origin', monkeypatch, kind)
    output = tmp_path/'bridge'
    result = runner.prepare(SimpleNamespace(input=origin, output=output))
    assert result['new_provider_calls'] == result['native_executions'] == 0
    return SimpleNamespace(input=output), runner.read(output/'prepared.json'), origin, calls


@pytest.mark.parametrize('kind', ['direct', 'atomic'])
def test_complete_old_raw_ledgers_revalidated_new_closure_and_only_metadata_added(tmp_path, monkeypatch, kind):
    args, protocol, origin, calls = prepared(tmp_path, monkeypatch, kind)
    old = runner.read(origin/'prepared.json')
    assert protocol['origin']['prepared'] == runner.frozen(origin/'prepared.json')
    assert protocol['algorithm_entrypoints']['driver'] == runner.frozen(runner.__file__)
    for case, previous in zip(protocol['cases'], old['cases']):
        assert [e['rank'] for e in case['candidates']] == [e['rank'] for e in previous['candidates']]
        for entry, before in zip(case['candidates'], previous['candidates']):
            current = runner.read(entry['program']['path']); original = runner.read(before['program']['path'])
            assert {k:v for k,v in current.items() if k != 'source_provenance'} == original
            assert entry['request'] == before['request'] and entry['analysis'] == before['analysis']
    runner._verify_protocol(protocol); runner._verify_algorithm(protocol)
    assert calls and not list(args.input.rglob('dispatch_claim.json'))


def test_first_failure_repeat_never_refills_after_unconfirmed_failure(tmp_path, monkeypatch):
    args, protocol, _, _ = prepared(tmp_path, monkeypatch)
    executed = []
    def execute(candidate, source, corpus, directory, protocol):
        assert candidate['source_provenance']['original_body']
        executed.append(candidate['id'])
        outcome = dict(transport=dict(status='matched'), native=dict(
            controls=dict(status='all_source_controls_passed'), controlled_failure=len(executed) == 1))
        runner.write(directory/'outcome.json', outcome)
        return outcome
    monkeypatch.setattr(runner, 'one_run', execute)
    summary = runner.run(args)
    assert len(executed) == 2 and len(set(executed)) == 1
    assert summary['detector_alerts'] == 0


@pytest.mark.parametrize('part', ['raw_generation', 'raw_review', 'entrypoint', 'algorithm', 'incomplete'])
def test_old_raw_hash_policy_and_entrypoint_failures_refuse_bridge(tmp_path, monkeypatch, part):
    origin, _ = original_run(tmp_path, monkeypatch)
    protocol = runner.read(origin/'prepared.json')
    if part in {'raw_generation', 'raw_review'}:
        parent = origin.parent if part == 'raw_generation' else origin
        path = next(parent.glob('cases/*/generation/completion/response.body')) if part == 'raw_generation' else next(parent.glob('cases/*/candidate_*/review/completion/response.body'))
        path.write_bytes(path.read_bytes()+b' ')
        with pytest.raises(ValueError): runner.verify_origin(origin)
    elif part == 'incomplete':
        (origin/'semantic_summary.json').unlink()
        with pytest.raises(FileNotFoundError): runner.verify_origin(origin)
    else:
        changed = copy.deepcopy(protocol)
        if part == 'entrypoint': changed['algorithm_entrypoints']['driver'] = runner.frozen(runner.__file__)
        else: next(iter(changed['algorithm'].values()))['sha256'] = '0'*64
        with pytest.raises(ValueError): runner._old_algorithm(changed)


def test_extra_loaded_module_or_metadata_body_change_refuses_new_closure(tmp_path, monkeypatch):
    args, protocol, _, _ = prepared(tmp_path, monkeypatch)
    bad = copy.deepcopy(protocol)
    key = next(key for key,row in bad['algorithm'].items() if row['path'] == str(Path(runner.__file__).resolve()))
    del bad['algorithm'][key]
    with pytest.raises(ValueError): runner._verify_algorithm(bad)
    case = next(c for c in protocol['cases'] if c['candidates'])
    entry = case['candidates'][0]
    path = Path(entry['program']['path']); candidate = runner.read(path)
    candidate['edits'][0]['after'] += '\n    assert False'
    path.write_text(__import__('json').dumps(candidate))
    entry['program'] = runner.frozen(path)
    with pytest.raises(ValueError): runner._verify_protocol(protocol)


def test_pending_missing_metadata_receipt_precedes_any_subject_execution(tmp_path, monkeypatch):
    origin, _ = original_run(tmp_path, monkeypatch)
    protocol = runner.read(origin/'prepared.json')
    case = next(c for c in protocol['cases'] if c['candidates'])
    entry = case['candidates'][0]
    candidate = runner.read(entry['program']['path'])
    pending = origin/'cases'/case['case']/f"candidate_{entry['rank']:04d}"/'initial/native'
    runner.write(pending/'emitted/stage.json', dict(stage='emit'))
    runner.write(pending/'prepared/candidates.json', dict(candidates=[candidate]))
    result = runner.prior_execution_boundary(origin, protocol)
    assert result['recorded_subject_executions'] == 0 and len(result['interrupted']) == 1
    assert result['interrupted'][0]['prepared_candidate'] == runner.frozen(pending/'prepared/candidates.json')
    runner.write(pending/'executed/runs.json', [])
    with pytest.raises(ValueError, match='Existing subject execution'):
        runner.prior_execution_boundary(origin, protocol)
