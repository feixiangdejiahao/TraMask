"""A timebox boundary must not be mistaken for achieving the quality objective."""
from datetime import datetime, timedelta, timezone

import pytest

from scripts.audit_fp_window_closing import phase_state


DEADLINE = datetime(2026,10,2,18,7,24,tzinfo=timezone.utc)


@pytest.mark.parametrize('offset,phase,finished',[
    (-1,'interim',False),
    (0,'final',True),
    (1,'final',True),
])
def test_allowed_boundary_records_window_status_separately_from_quality(offset,phase,finished):
    state = phase_state(DEADLINE+timedelta(microseconds=offset),DEADLINE,phase)
    assert state['bounded_window_finished'] is finished
    assert state['objective_achieved'] is False
    assert state['quality_objective_achieved'] is False
    assert state['phase'] == phase


@pytest.mark.parametrize('offset,phase',[(-1,'final'),(0,'interim'),(1,'interim')])
def test_wrong_side_of_boundary_is_rejected_immediately(offset,phase):
    with pytest.raises(ValueError,match='phase requires'):
        phase_state(DEADLINE+timedelta(microseconds=offset),DEADLINE,phase)


def test_default_is_interim_and_naive_time_is_not_accepted():
    assert phase_state(DEADLINE-timedelta(seconds=1),DEADLINE)['phase'] == 'interim'
    with pytest.raises(ValueError,match='timezone-aware'):
        phase_state(DEADLINE.replace(tzinfo=None),DEADLINE,'final')
