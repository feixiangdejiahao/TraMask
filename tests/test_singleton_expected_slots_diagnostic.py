from concurrent.futures import ThreadPoolExecutor
import threading
import time

import pytest

from scripts import run_singleton_expected_slots_diagnostic as runner


def prepared(tmp_path, *, window=360):
    for name in ['protocol.json','summary.json']:
        runner.write(tmp_path/name, {})
    protocol = dict(preparation_protocol_sha256=runner.digest(tmp_path/'protocol.json'),
        preparation_summary_sha256=runner.digest(tmp_path/'summary.json'),code_sha256={},
        max_workers=2,launch_window_seconds=window,
        records=[dict(index=i,case='unlabeled',request=str(i),status='prepared_hypothesis')
                 for i in range(4)]+[dict(index=4,case='unlabeled',status='unknown_no_editable_slot'),
                                    dict(index=5,case='unlabeled',status='unknown_context_budget')])
    runner.write(tmp_path/'execution_protocol.json',protocol)
    runner.write(tmp_path/'execution_protocol.seal.json',
                 dict(sha256=runner.digest(tmp_path/'execution_protocol.json')))


def test_bounded_dispatch_retains_unknown_parents_and_does_not_retry(tmp_path,monkeypatch):
    prepared(tmp_path)
    active,maximum,calls = 0,0,[]
    lock = threading.Lock()
    def fake(row,directory,started):
        nonlocal active,maximum
        with lock:
            active += 1
            maximum = max(maximum,active)
            calls.append(row['index'])
        time.sleep(.01)
        with lock:
            active -= 1
        return dict(index=row['index'],case=row['case'],status='complete',strict_json_valid=True,
            adapter_status='preserve',accepted_revisions=0,external_model_calls=1,
            elapsed_seconds=.01,expected_wire_payload_matches=True)
    monkeypatch.setattr(runner,'one',fake)
    result = runner.run(tmp_path)
    assert maximum == 2 and sorted(calls) == list(range(4))
    assert result['parent_denominator'] == 6 and result['external_model_calls'] == 4
    assert result['statuses']['unknown_no_editable_slot'] == 1
    assert result['statuses']['unknown_context_budget'] == 1
    assert result['correctness_evaluated'] is False
    with pytest.raises(ValueError,match='cannot be restarted'):
        runner.run(tmp_path)


def test_launch_window_ends_without_dropping_requests(tmp_path,monkeypatch):
    prepared(tmp_path,window=0)
    monkeypatch.setattr(runner,'one',lambda *args: pytest.fail('No dispatch after launch window'))
    result = runner.run(tmp_path)
    assert result['launched'] == 0
    assert result['statuses']['not_launched_budget'] == 4
    assert result['parent_denominator'] == 6


def test_modified_protocol_fails_before_provider(tmp_path,monkeypatch):
    prepared(tmp_path)
    runner.write(tmp_path/'summary.json',dict(changed=True))
    monkeypatch.setattr(runner,'one',lambda *args: pytest.fail('No dispatch on changed inputs'))
    with pytest.raises(ValueError,match='Frozen artifact changed'):
        runner.run(tmp_path)
    assert not (tmp_path/'launch.json').exists()
