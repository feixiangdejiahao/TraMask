import copy

import pytest

from scripts import run_negative_template_ablation as ablation


def outcome(failed=False, controls='all_source_controls_passed'):
    return dict(transport=dict(status='matched'),
                native=dict(controls=dict(status=controls), controlled_failure=failed))


def fixture(statuses=('eligible', 'eligible'), first_fails=False):
    entries = [dict(rank=i, program=dict(path=f'p{i}', sha256=str(i))) for i in (1, 2)]
    case = dict(case='sample', candidates=entries)
    attempts = [dict(rank=e['rank'], program=e['program'], initial=outcome(),
                     initial_receipt=dict(path=f"initial{e['rank']}", sha256=str(e['rank']))) for e in entries]
    failed = attempts[0 if first_fails else 1]
    failed.update(initial=outcome(True), confirmation=outcome(True),
                  confirmation_receipt=dict(path='repeat', sha256='repeat'))
    if first_fails:
        attempts = attempts[:1]
    decisions = {('sample', e['rank']): dict(admitted=True, decision=dict(path=f"decision{e['rank']}")) for e in entries}
    alert = dict(program=failed['program'], initial=failed['initial_receipt'],
                 confirmation=failed['confirmation_receipt'], semantic=decisions['sample', failed['rank']]['decision'],
                 validity='pending_independent_full_test_audit')
    source = dict(case='sample', attempts=attempts, alert=alert)
    classes = {('sample', e['rank']): dict(status=status) for e, status in zip(entries, statuses)}
    return case, source, decisions, classes


def test_same_eligible_prefix_transfers_the_whole_alert_and_does_not_mutate_source():
    args = fixture()
    before = copy.deepcopy(args)
    result = ablation.replay_case(*args)
    assert result['alert'] == args[1]['alert']
    assert result['attempts'] == args[1]['attempts']
    assert args == before


def test_withholding_all_templates_emits_no_alert_but_retains_source_record():
    args = fixture(('withheld', 'unknown'))
    result = ablation.replay_case(*args)
    assert result['alert'] is None and result['attempts'] == []
    assert args[1]['alert'] is not None


def test_a_rejected_source_failure_cannot_be_replaced_by_an_unexecuted_candidate():
    result = ablation.replay_case(*fixture(('withheld', 'eligible'), first_fails=True))
    assert result['alert'] is None
    assert result['stop_reason'] == 'required_native_prefix_not_observed'


def test_missing_required_prefix_cannot_be_skipped_to_a_later_archived_failure():
    args = fixture()
    args[1]['attempts'].pop(0)
    result = ablation.replay_case(*args)
    assert result['alert'] is None and result['attempts'] == []


def test_unconfirmed_first_failure_stops_even_with_a_later_archived_failure():
    args = fixture()
    args[1]['attempts'][0]['initial'] = outcome(True)
    result = ablation.replay_case(*args)
    assert result['alert'] is None and len(result['attempts']) == 1
    assert result['stop_reason'] == 'first_failure_unconfirmed'


def test_unavailable_source_control_stops_before_later_failure():
    args = fixture()
    args[1]['attempts'][0]['initial'] = outcome(False, 'source_control_failed')
    result = ablation.replay_case(*args)
    assert result['alert'] is None and len(result['attempts']) == 1


def test_source_semantic_rejection_cannot_be_turned_into_admission():
    args = fixture()
    args[2]['sample', 2]['admitted'] = False
    assert ablation.replay_case(*args)['alert'] is None


def test_forged_partial_alert_is_rejected():
    args = fixture()
    del args[1]['alert']['semantic']
    with pytest.raises(ValueError, match='complete archived alert'):
        ablation.replay_case(*args)


def test_complete_cohort_and_all_source_candidates_are_required():
    case, source, decisions, classes = fixture()
    base = dict(cases=[case]); summary = dict(results=[source])
    semantic = dict(results=[dict(case=k[0], rank=k[1], **v) for k, v in decisions.items()])
    rows = [dict(case='sample', rank=e['rank'], program=e['program'], classification=classes['sample', e['rank']])
            for e in case['candidates']]
    assert ablation.derive(base, summary, semantic, rows)[0]['alert'] == source['alert']
    with pytest.raises(ValueError, match='all source candidates'):
        ablation.derive(base, summary, semantic, rows[:1])
    with pytest.raises(ValueError, match='complete declared cohort'):
        ablation.derive(base, dict(results=[]), semantic, rows)
