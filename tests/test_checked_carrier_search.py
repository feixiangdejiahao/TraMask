from types import SimpleNamespace

from scripts import run_checked_carrier_search as runner


def outcome(status='pass', controls='all_source_controls_passed', transport='matched'):
    return dict(transport=dict(status=transport), native=dict(
        controls=dict(status=controls), tests=[dict(status=status)], parser_errors=[],
        controlled_failure=status == 'fail' and controls == 'all_source_controls_passed'))


def prepared(tmp_path):
    source = tmp_path/'source'
    runner.write(source/'corpus.json', {})
    root = tmp_path/'run'
    entries = []
    for rank in [1, 2]:
        folder = root/'cases'/'trial'/f'candidate_{rank:04d}'
        runner.write(folder/'program.json', dict(id=f'candidate{rank}'))
        runner.write(folder/'probe.json', dict(id=f'probe{rank}'))
        entries.append(dict(rank=rank, program=runner.frozen(folder/'program.json'),
                            probe=runner.frozen(folder/'probe.json')))
    runner.write(root/'generation.json', {})
    runner.write(root/'prepared.json', dict(algorithm={}, deadline_utc='2099-01-01T00:00:00Z',
        timeout=1, max_native_executions=10, trial_denominator=1,
        cases=[dict(case='trial', source=str(source), inputs={},
                    generation=runner.frozen(root/'generation.json'), candidates=entries,
                    status='source_candidates')]))
    runner.write(root/'seal.json', runner.frozen(root/'prepared.json'))
    return root


def install_native(monkeypatch, statuses):
    calls = []
    def native(candidate, source, corpus, directory, protocol):
        key = candidate['id'], directory.name
        calls.append(key)
        result = outcome(statuses.get(key, 'pass'))
        runner.write(directory/'outcome.json', result)
        return result
    monkeypatch.setattr(runner, 'one_run', native)
    return calls


def test_failed_adapter_is_not_an_alert_and_cannot_run_its_candidate(tmp_path, monkeypatch):
    root = prepared(tmp_path)
    calls = install_native(monkeypatch, {('probe1', 'probe'): 'fail',
        ('candidate2', 'initial'): 'fail', ('candidate2', 'confirmation'): 'fail'})
    result = runner.run(SimpleNamespace(input=root))
    assert result['detector_alerts'] == 1
    assert calls == [('probe1', 'probe'), ('probe2', 'probe'),
                     ('candidate2', 'initial'), ('candidate2', 'confirmation')]
    alert = runner.read(root/'cases'/'trial'/'result.json')['alert']
    assert runner.read(alert['program']['path'])['id'] == 'candidate2'


def test_first_candidate_failure_stops_trial_when_confirmation_passes(tmp_path, monkeypatch):
    root = prepared(tmp_path)
    calls = install_native(monkeypatch, {('candidate1', 'initial'): 'fail'})
    result = runner.run(SimpleNamespace(input=root))
    assert result['detector_alerts'] == 0
    assert calls == [('probe1', 'probe'), ('candidate1', 'initial'), ('candidate1', 'confirmation')]
    assert runner.read(root/'cases'/'trial'/'result.json')['stop_reason'] == 'first_failure_unconfirmed'


def test_empty_skipped_errored_unmatched_or_uncontrolled_probe_is_not_a_precondition():
    assert runner.passed(outcome())
    assert not runner.passed(outcome(status='skip'))
    assert not runner.passed(outcome(controls='missing'))
    assert not runner.passed(outcome(transport='mismatch'))
    row = outcome()
    row['native']['tests'] = []
    assert not runner.passed(row)
    row = outcome()
    row['native']['parser_errors'] = ['bad']
    assert not runner.passed(row)
