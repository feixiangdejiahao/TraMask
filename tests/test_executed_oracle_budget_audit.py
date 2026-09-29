"""Eligibility depends on completed execution and source controls, not outcome polarity."""
import copy

import pytest

from scripts.audit_executed_oracle_budget import execution_gate


def record(identifier,status='pass',executed=True,control=True):
    return dict(candidate_id=identifier,executed=executed,control_and_seed_valid=control,
                candidate_outcomes=[dict(executed=executed,statuses=[status],report_errors=[])])


def test_pass_and_fail_are_equal_admission_and_every_input_is_retained():
    candidates=[dict(id=name) for name in ['pass','fail','not_run','error','bad_control','missing']]
    rows=[record('pass'),record('fail','fail'),record('not_run','pass',False),
          record('error','error'),record('bad_control','fail',True,False)]
    before=copy.deepcopy((candidates,rows));result=execution_gate(candidates,dict(current_results=rows))
    assert {c['id'] for c in result['admitted']}=={'pass','fail'}
    assert {c['id'] for c in result['retained_pending']}=={'not_run','error','bad_control','missing'}
    assert result['counts']==dict(executed_control_valid=2,execution_unknown=3,executed_control_unconfirmed=1)
    assert (candidates,rows)==before


def test_labels_and_failure_text_do_not_change_membership():
    candidates=[dict(id='a'),dict(id='b')];rows=[record('a'),record('b','fail')]
    initial=execution_gate(candidates,dict(current_results=rows))
    candidates[0]['evaluation_target']=True;rows[0]['oracle_correct']=False
    rows[1]['failure_message']='Any target keyword is ignored.'
    changed=execution_gate(candidates,dict(current_results=rows))
    assert initial['records']==changed['records'] and initial['counts']==changed['counts']


def test_compiler_not_run_remains_unknown_even_when_control_is_marked_valid():
    row=record('a','error',False,True)
    row['candidate_outcomes'][0]['report_errors']=['isolated_go_not_run']
    result=execution_gate([dict(id='a')],dict(current_results=[row]))
    assert result['records'][0]['category']=='execution_unknown'
    assert result['retained_pending']==[dict(id='a')]


def test_duplicate_outcomes_require_explicit_aggregation():
    with pytest.raises(ValueError,match='duplicate'):
        execution_gate([dict(id='a')],dict(current_results=[record('a'),record('a','fail')]))
