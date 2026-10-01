"""Recorded bounded dispatch/resume behavior with no external requests."""
import json
from types import SimpleNamespace

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
