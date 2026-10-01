"""Recorded bounded dispatch/resume behavior with no external requests."""
import json
import importlib
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
from types import ModuleType
from types import SimpleNamespace

import pytest

from scripts import run_test_admission as driver


def frozen_query(tmp_path, count=2, tokens=1000, calls=2):
    items = []
    for index in range(count):
        folder = tmp_path/f'item_{index:04}'
        folder.mkdir()
        request = dict(id=str(index), system='S', prompt='P', thinking='disabled',
                       max_tokens=100, check_ids=['P', 'Q0'])
        (folder/'request.json').write_text(json.dumps(request))
        items.append(dict(name=folder.name, key=f'toy:{index}', case='toy',
                          candidate_id=str(index), request_path=str(folder/'request.json'),
                          request_sha256=driver.digest(folder/'request.json')))
    (tmp_path/'prepared.json').write_text(json.dumps(dict(items=items,
        max_model_calls=calls, max_total_tokens=tokens, experiment='toy applicability')))
    return SimpleNamespace(input=tmp_path)


def fake_provider(monkeypatch, usage=100, completed=True):
    calls = []
    def dispatch(request, output, root):
        calls.append(request)
        output.mkdir()
        manifest = dict(status='complete' if completed else 'error', external_model_calls=1,
                        request_id=request['id'],
                        finish_reason='stop', usage=dict(total_tokens=usage) if usage is not None else None)
        (output/'manifest.json').write_text(json.dumps(manifest))
        if completed:
            (output/'completion.txt').write_text('{"P":"supported","Q0":"supported"}')
    monkeypatch.setattr(driver, 'dispatch', dispatch)
    return calls


def test_resume_never_resends_queries_or_changes_decisions(tmp_path, monkeypatch):
    args = frozen_query(tmp_path)
    calls = fake_provider(monkeypatch)
    first = driver.run(args)
    second = driver.run(args)
    assert len(calls) == 2
    assert first == second
    assert first['provider_calls'] == 2 and first['accounted_tokens'] == 200


def test_token_reservation_stops_before_dispatch_and_remains_visible(tmp_path, monkeypatch):
    args = frozen_query(tmp_path, tokens=50)
    calls = fake_provider(monkeypatch)
    result = driver.run(args)
    assert not calls and result['provider_calls'] == 0
    rows = driver.read(tmp_path/'summary.json')['decisions']
    assert all(row['decision']['reason'] == 'model_budget' for row in rows)


def test_call_budget_does_not_hide_unreviewed_candidates(tmp_path, monkeypatch):
    args = frozen_query(tmp_path, calls=1)
    calls = fake_provider(monkeypatch)
    result = driver.run(args)
    assert len(calls) == result['provider_calls'] == 1
    rows = driver.read(tmp_path/'summary.json')['decisions']
    assert rows[0]['decision']['alarm_eligible']
    assert rows[1]['decision']['reason'] == 'model_budget'


def test_missing_usage_is_reserved_and_failed_request_is_not_retried(tmp_path, monkeypatch):
    args = frozen_query(tmp_path)
    calls = fake_provider(monkeypatch, usage=None, completed=False)
    result = driver.run(args)
    assert result['usage_missing'] == 2 and result['accounted_tokens'] == 716
    again = driver.run(args)
    assert len(calls) == 2 and again == result
    assert all(not row['decision']['alarm_eligible'] for row in driver.read(tmp_path/'summary.json')['decisions'])


def fake_method(tmp_path, name, *, prompt='P', on_prepare=None):
    module = ModuleType(name)
    source = tmp_path/(name.rsplit('.', 1)[-1]+'.py')
    source.write_text('VALUE = 1\n')
    module.__file__ = str(source)
    module.prepared, module.decided = [], []
    def prepare(corpus, frontend, candidate, issue, **kwargs):
        module.prepared.append((corpus, frontend, candidate, issue, kwargs))
        if on_prepare:
            on_prepare()
        return dict(status='prepared', prompt_bytes=2, request=dict(
            id='module-original-id', system='S', prompt=prompt,
            thinking='enabled', max_tokens=123, check_ids=['P']))
    def decide(request, payload, *, finish_reason):
        module.decided.append((request, payload, finish_reason))
        return dict(status=name, alarm_eligible=True, request_id=request['id'])
    module.prepare, module.decide = prepare, decide
    return module


def prepare_inputs(tmp_path, monkeypatch, module, *, method='legacy', **overrides):
    corpus = tmp_path/'corpus.json'
    frontend = tmp_path/'frontend.json'
    candidates = tmp_path/'candidates.json'
    corpus.write_text('{"language":"python"}')
    frontend.write_text('{}')
    candidates.write_text('[{"id":"candidate","edits":[]}]')
    (tmp_path/'issue.md').write_text('Source issue contract')
    baseline = tmp_path/'baseline.json'
    baseline.write_text('{}')
    row = dict(key='toy:0:candidate', case='toy', candidate_id='candidate',
        inputs={name: dict(path=str(path), sha256=driver.digest(path))
                for name, path in [('corpus', corpus), ('frontend', frontend), ('candidates', candidates)]})
    monkeypatch.setattr(driver, 'selected_records', lambda baseline, scope: [row])
    monkeypatch.setattr(driver, '_method', lambda name: module)
    values = dict(input=baseline, output=tmp_path/'prepared', scope='positive',
        method=method, thinking='disabled', reasoning_effort=None,
        max_prompt_bytes=64000, output_token_limit=100, max_model_calls=2,
        max_total_tokens=10000, deadline_utc=None)
    values.update(overrides)
    return SimpleNamespace(**values)


def test_new_prepare_defaults_legacy_and_seals_final_dispatch_identity(tmp_path, monkeypatch):
    module = fake_method(tmp_path, driver.METHODS['legacy'])
    args = prepare_inputs(tmp_path, monkeypatch, module)
    del args.method
    driver.prepare(args)
    prepared = driver.read(args.output/'prepared.json')
    request = driver.read(prepared['items'][0]['request_path'])
    assert prepared['method_module'] == driver.METHODS['legacy']
    assert request['thinking'] == 'disabled' and request['max_tokens'] == 100
    assert 'reasoning_effort' not in request
    assert request['id'] == driver._request_identity(request) != 'module-original-id'
    assert prepared['algorithm_entry_modules'][driver.METHODS['legacy']]['sha256'] == driver.digest(module.__file__)
    assert 'relation_search.test_role_summaries' in prepared['imported_source_modules']


def test_guarded_decision_uses_frozen_module_despite_run_flag(tmp_path, monkeypatch):
    guarded = fake_method(tmp_path, driver.METHODS['guarded'])
    legacy = fake_method(tmp_path, driver.METHODS['legacy'])
    args = prepare_inputs(tmp_path, monkeypatch, guarded, method='guarded')
    driver.prepare(args)
    monkeypatch.setattr(driver, '_method', lambda name: guarded if name == driver.METHODS['guarded'] else legacy)
    calls = fake_provider(monkeypatch)
    result = driver.run(SimpleNamespace(input=args.output, method='legacy'))
    assert len(calls) == 1 and len(guarded.decided) == 1 and not legacy.decided
    assert result['method_module'] == driver.METHODS['guarded']
    assert driver.read(args.output/'summary.json')['decisions'][0]['decision']['status'] == driver.METHODS['guarded']


def test_same_named_decider_cannot_switch_to_different_source_file(tmp_path, monkeypatch):
    guarded = fake_method(tmp_path, driver.METHODS['guarded'])
    args = prepare_inputs(tmp_path, monkeypatch, guarded, method='guarded')
    driver.prepare(args)
    other = fake_method(tmp_path, driver.METHODS['legacy'])
    monkeypatch.setattr(driver, '_method', lambda name: other)
    calls = fake_provider(monkeypatch)
    with pytest.raises(ValueError, match='Sealed admission module binding changed'):
        driver.run(SimpleNamespace(input=args.output))
    assert not calls


@pytest.mark.parametrize('thinking,effort', [('disabled', None), ('enabled', 'low'), ('enabled', 'high'), ('enabled', 'max')])
def test_request_settings_are_actual_dispatch_settings(tmp_path, monkeypatch, thinking, effort):
    module = fake_method(tmp_path, driver.METHODS['legacy'])
    args = prepare_inputs(tmp_path, monkeypatch, module, thinking=thinking, reasoning_effort=effort)
    driver.prepare(args)
    calls = fake_provider(monkeypatch)
    driver.run(SimpleNamespace(input=args.output))
    request = calls[0]
    assert request['thinking'] == thinking and request.get('reasoning_effort') == effort
    assert request['max_tokens'] == args.output_token_limit
    assert request['id'] == driver._request_identity(request)


def test_request_id_changes_with_each_payload_setting_without_mutating_original():
    original = dict(id='original', query_sha256='original', system='S', prompt='P', thinking='disabled', max_tokens=12)
    args = SimpleNamespace(thinking='disabled', reasoning_effort=None, output_token_limit=100)
    normal = driver._configure_request(original, args)
    variants = [dict(normal, system='different'), dict(normal, prompt='different'),
                dict(normal, thinking='enabled'), dict(normal, max_tokens=101),
                dict(normal, reasoning_effort='low')]
    assert len({normal['id'], *[driver._request_identity(value) for value in variants]}) == 6
    assert normal['query_sha256'] == normal['id']
    assert original['id'] == 'original' and original['max_tokens'] == 12
    assert original['query_sha256'] == 'original'


def test_changed_frozen_request_bytes_are_rejected_before_dispatch(tmp_path, monkeypatch):
    args = frozen_query(tmp_path, count=1)
    path = tmp_path/'item_0000/request.json'
    request = driver.read(path)
    request['prompt'] = 'changed'
    path.write_text(json.dumps(request))
    calls = fake_provider(monkeypatch)
    with pytest.raises(ValueError, match='Frozen semantic request changed'):
        driver.run(args)
    assert not calls


def test_outer_hash_rewrite_cannot_hide_wrong_actual_dispatch_id(tmp_path, monkeypatch):
    module = fake_method(tmp_path, driver.METHODS['legacy'])
    args = prepare_inputs(tmp_path, monkeypatch, module)
    driver.prepare(args)
    prepared_path = args.output/'prepared.json'
    prepared = driver.read(prepared_path)
    path = Path(prepared['items'][0]['request_path'])
    request = driver.read(path)
    request['thinking'] = 'enabled'
    path.write_text(json.dumps(request))
    prepared['items'][0]['request_sha256'] = driver.digest(path)
    prepared_path.write_text(json.dumps(prepared))
    calls = fake_provider(monkeypatch)
    with pytest.raises(ValueError, match='actual request fields'):
        driver.run(SimpleNamespace(input=args.output))
    assert not calls


def test_runner_does_not_truncate_module_oversized_request(tmp_path, monkeypatch):
    module = fake_method(tmp_path, driver.METHODS['legacy'], prompt='long complete test')
    args = prepare_inputs(tmp_path, monkeypatch, module, max_prompt_bytes=5)
    result = driver.prepare(args)
    assert result['requests'] == 0
    analysis = driver.read(args.output/'item_0000/analysis.json')
    assert analysis['status'] == 'unknown_prompt_budget' and not analysis['truncated']
    assert analysis['required_bytes'] == len('S'.encode()) + len('long complete test'.encode())


def test_deadline_refuses_new_requests_and_retains_every_unknown(tmp_path, monkeypatch):
    now = datetime(2026, 10, 1, tzinfo=timezone.utc)
    args = frozen_query(tmp_path)
    args.deadline_utc = (now + timedelta(seconds=299)).isoformat()
    monkeypatch.setattr(driver, '_utc_now', lambda: now)
    calls = fake_provider(monkeypatch)
    result = driver.run(args)
    rows = driver.read(tmp_path/'summary.json')['decisions']
    assert not calls and result['provider_calls'] == 0
    assert len(rows) == 2 and all(row['decision']['reason'] == 'deadline' for row in rows)
    assert all(row['decision']['required_seconds'] == 300 for row in rows)
    monkeypatch.setattr(driver, '_utc_now', lambda: now + timedelta(hours=1))
    assert driver.run(SimpleNamespace(input=tmp_path)) == result
    assert not calls


def test_exactly_300_seconds_allows_dispatch_and_expired_resume_reads_receipt(tmp_path, monkeypatch):
    now = datetime(2026, 10, 1, tzinfo=timezone.utc)
    args = frozen_query(tmp_path, count=1)
    args.deadline_utc = (now + timedelta(seconds=300)).isoformat()
    monkeypatch.setattr(driver, '_utc_now', lambda: now)
    calls = fake_provider(monkeypatch)
    first = driver.run(args)
    assert len(calls) == 1
    monkeypatch.setattr(driver, '_utc_now', lambda: now + timedelta(hours=1))
    assert driver.run(args) == first and len(calls) == 1


def test_prepared_earlier_deadline_cannot_be_extended_by_run_flag(tmp_path, monkeypatch):
    now = datetime(2026, 10, 1, tzinfo=timezone.utc)
    args = frozen_query(tmp_path, count=1)
    path = tmp_path/'prepared.json'
    prepared = driver.read(path)
    prepared['deadline_utc'] = (now + timedelta(seconds=299)).isoformat()
    path.write_text(json.dumps(prepared))
    args.deadline_utc = (now + timedelta(hours=1)).isoformat()
    monkeypatch.setattr(driver, '_utc_now', lambda: now)
    calls = fake_provider(monkeypatch)
    driver.run(args)
    assert not calls


def test_wrong_provider_receipt_request_id_is_rejected(tmp_path, monkeypatch):
    args = frozen_query(tmp_path, count=1)
    folder = tmp_path/'item_0000/completion'
    folder.mkdir()
    (folder/'manifest.json').write_text(json.dumps(dict(status='complete', request_id='other', external_model_calls=1)))
    (folder/'completion.txt').write_text('{"P":"supported","Q0":"supported"}')
    calls = fake_provider(monkeypatch)
    with pytest.raises(ValueError, match='different frozen request'):
        driver.run(args)
    assert not calls


def sealing_fixture(tmp_path, monkeypatch, *, change_during_prepare=False, late_import=False):
    root = tmp_path/'source'
    root.mkdir()
    monkeypatch.setattr(driver, 'ROOT', root)
    monkeypatch.setattr(importlib.import_module('scripts.evaluate_test_validity'), 'ROOT', root)
    monkeypatch.syspath_prepend(str(root))
    name = 'runner_seal_late' if late_import else 'runner_seal_dependency'
    helper = root/(name+'.py')
    helper.write_text('VALUE = 1\n')
    method_source = root/'guarded.py'
    method_source.write_text('def lazy():\n    from '+name+' import VALUE\n' if not late_import else 'def dynamic(name):\n    return name\n')
    def action():
        importlib.import_module(name)
        if change_during_prepare:
            helper.write_text('VALUE = 2\n')
    module = fake_method(tmp_path, driver.METHODS['guarded'], on_prepare=action)
    module.__file__ = str(method_source)
    args = prepare_inputs(tmp_path, monkeypatch, module, method='guarded')
    monkeypatch.delitem(sys.modules, name, raising=False)
    return args, helper, name


def test_transitive_lazy_import_is_preloaded_and_source_sha_sealed(tmp_path, monkeypatch):
    args, helper, name = sealing_fixture(tmp_path, monkeypatch)
    driver.prepare(args)
    prepared = driver.read(args.output/'prepared.json')
    assert prepared['imported_source_modules'][name]['sha256'] == driver.digest(helper)
    assert helper.relative_to(driver.ROOT).as_posix() in prepared['algorithm']


def test_changed_transitive_source_aborts_preparation(tmp_path, monkeypatch):
    args, _, _ = sealing_fixture(tmp_path, monkeypatch, change_during_prepare=True)
    with pytest.raises(ValueError, match='imported source changed'):
        driver.prepare(args)
    assert not (args.output/'prepared.json').exists()


def test_unsealed_dynamic_local_import_is_not_silently_accepted(tmp_path, monkeypatch):
    args, _, _ = sealing_fixture(tmp_path, monkeypatch, late_import=True)
    with pytest.raises(ValueError, match='Local source imported after the seal'):
        driver.prepare(args)
    assert not (args.output/'prepared.json').exists()


def test_changed_sealed_decider_source_aborts_run_without_external_request(tmp_path, monkeypatch):
    module = fake_method(tmp_path, driver.METHODS['guarded'])
    args = prepare_inputs(tmp_path, monkeypatch, module, method='guarded')
    driver.prepare(args)
    Path(module.__file__).write_text('VALUE = 2\n')
    calls = fake_provider(monkeypatch)
    with pytest.raises(ValueError, match='imported source changed'):
        driver.run(SimpleNamespace(input=args.output))
    assert not calls


def enrichment_fixture(tmp_path, monkeypatch):
    from relation_search import source_dependencies
    module = fake_method(tmp_path, driver.METHODS['guarded'])
    args = prepare_inputs(tmp_path, monkeypatch, module, method='guarded', enrich_repository_sources=True)
    repository = tmp_path/'repository'
    repository.mkdir()
    (repository/'test_check.py').write_text('raise RuntimeError("different disk test")\n')
    marker = 'raise RuntimeError("source must never execute")\nVALUE = 41\n'
    (repository/'helper.py').write_text(marker)
    corpus = dict(language='python', sources={
        'test_check.py': dict(code='import helper\n', language='python', origin='repository')})
    Path(args.input.parent/'corpus.json').write_text(json.dumps(corpus))
    (tmp_path/'case.json').write_text(json.dumps(dict(repository=str(repository))))
    candidates = tmp_path/'candidates.json'
    candidates.write_text('[{"id":"candidate","edits":[]},{"id":"second","edits":[]}]')
    inputs = {name: dict(path=str(tmp_path/(name+'.json')), sha256=driver.digest(tmp_path/(name+'.json')))
              for name in ['corpus', 'frontend', 'candidates']}
    rows = [dict(key='toy:0:'+identifier, case='toy', candidate_id=identifier, inputs=inputs)
            for identifier in ['candidate', 'second']]
    monkeypatch.setattr(driver, 'selected_records', lambda baseline, scope: rows)
    calls = []
    original = source_dependencies.enrich_sources
    def enrich(corpus, frontend, repository, **kwargs):
        calls.append(kwargs)
        return original(corpus, frontend, repository, **kwargs)
    monkeypatch.setattr(source_dependencies, 'enrich_sources', enrich)
    return args, module, corpus, calls, marker


def test_optional_enrichment_cached_for_round_and_local_artifact_sealed(tmp_path, monkeypatch):
    args, module, original, calls, marker = enrichment_fixture(tmp_path, monkeypatch)
    driver.prepare(args)
    prepared = driver.read(args.output/'prepared.json')
    assert len(calls) == 1
    assert {row['id'] for row in calls[0]['candidates']} == {'candidate', 'second'}
    assert calls[0]['max_added_files'] == 256 and calls[0]['max_depth'] == 8
    assert len(prepared['source_context_artifacts']) == 1
    assert prepared['items'][0]['source_context'] == prepared['items'][1]['source_context']
    receipt = prepared['source_context_artifacts'][0]
    assert driver.digest(receipt['path']) == receipt['sha256']
    artifact = driver.read(receipt['path'])
    assert artifact['case_metadata']['sha256'] == driver.digest(tmp_path/'case.json')
    assert artifact['added_sources']['helper.py']['code'] == marker
    for call in module.prepared:
        assert call[0]['sources']['test_check.py'] == original['sources']['test_check.py']
    request = driver.read(prepared['items'][0]['request_path'])
    assert marker not in request['prompt'] and 'source_context' not in request


def test_source_enrichment_cannot_replace_frozen_original_even_in_place(tmp_path, monkeypatch):
    from relation_search import source_dependencies
    args, _, _, _, _ = enrichment_fixture(tmp_path, monkeypatch)
    def replace(corpus, *unused, **kwargs):
        corpus['sources']['test_check.py']['code'] = 'changed'
        return corpus, {}
    monkeypatch.setattr(source_dependencies, 'enrich_sources', replace)
    with pytest.raises(ValueError, match='replaced a frozen original source'):
        driver.prepare(args)


def test_changed_source_enrichment_artifact_aborts_before_provider_call(tmp_path, monkeypatch):
    args, _, _, _, _ = enrichment_fixture(tmp_path, monkeypatch)
    driver.prepare(args)
    prepared = driver.read(args.output/'prepared.json')
    Path(prepared['source_context_artifacts'][0]['path']).write_text('{}')
    calls = fake_provider(monkeypatch)
    with pytest.raises(ValueError, match='source enrichment artifact changed'):
        driver.run(SimpleNamespace(input=args.output))
    assert not calls


def test_legacy_existing_summary_can_resume_with_original_shape(tmp_path, monkeypatch):
    args = frozen_query(tmp_path, count=1)
    calls = fake_provider(monkeypatch)
    first = driver.run(args)
    summary = driver.read(tmp_path/'summary.json')
    assert 'method_module' not in summary and 'runner_constraints' not in summary
    assert driver.run(args) == first and len(calls) == 1
