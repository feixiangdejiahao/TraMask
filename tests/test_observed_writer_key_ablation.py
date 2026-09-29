from copy import deepcopy

from scripts.ablate_observed_writer_key import replay_rows
from test_observed_write_frontier import event


def rows(first, second):
    return [dict(event=first, role='control', owner={'representative': 'control:source'}),
            dict(event=second, role='generated', owner={'representative': 'generated:child'})]


def test_same_value_different_writer_can_change_retention_in_this_ablation():
    first, second = event(), event()
    second['source_last_observed_writer']['start_byte'] += 1
    supplied = rows(first, second)
    frozen = deepcopy(supplied)
    writer = replay_rows(supplied, with_writer=True)
    value = replay_rows(supplied, with_writer=False)
    assert writer['summary']['retained_generated_candidates'] == 1
    assert value['summary']['retained_generated_candidates'] == 0
    assert supplied == frozen


def test_different_values_remain_distinct_when_writer_is_removed():
    first, second = event(), event()
    second['source_last_observed_writer']['start_byte'] += 1
    second['value']['value'] = False
    for arm in (True, False):
        result = replay_rows(rows(first, second), with_writer=arm)
        assert result['summary']['retained_generated_candidates'] == 1
        assert result['summary']['state_count'] == 2


def test_unknown_writer_does_not_gain_eligibility_in_value_arm():
    first, second = event(), event()
    del second['source_last_observed_writer']
    for arm in (True, False):
        result = replay_rows(rows(first, second), with_writer=arm)
        assert result['summary']['retained_generated_candidates'] == 0
        assert result['summary']['counters']['generated_unknown_or_unmapped'] == 1


def test_control_precedence_and_per_q_counts_stay_separate():
    first, second = event(), event()
    second['source_q_span']['start_byte'] += 1
    supplied = rows(first, second)
    supplied.append(dict(event=deepcopy(second), role='generated',
                         owner={'representative': 'generated:later'}))
    for arm in (True, False):
        result = replay_rows(supplied, with_writer=arm)
        assert result['summary']['generated_representatives'] == ['generated:child']
        assert len(result['summary']['per_source_q']) == 2
        assert not result['decisions'][-1]['retained']
