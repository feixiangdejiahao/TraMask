import json
import pytest

from augmentation.detection import parse_decision,run_detection
from test_agent import subject,provider_script


def decision():
    return {"action":"decide","decision":"gap","reason":"Joint condition returns the wrong result.",
            "combination":"Both arguments positive in one call.","expected_behavior":"Return one.",
            "current_behavior":"Returns zero.","validation_gap":"Original test checks only one positive argument.",
            "evidence":[{"path":"lib.py","start_line":1,"end_line":4,"fact":"Both-positive branch returns zero."}],
            "existing_test_ids":[]}


def test_detection_can_claim_gap_without_generating_or_running_tests(tmp_path):
    prepared,candidate=subject(tmp_path)
    prepared["candidates"]=[candidate]
    calls=[]
    result=run_detection(prepared,tmp_path/"detection",provider=provider_script([
        {"action":"inspect","reason":"Check tests","query":{"kind":"tests","path":"test_lib.py"}},decision()],calls))
    assert result["results"][0]["decision"]=="gap" and len(calls)==2
    assert result["test_generation_calls"]==result["test_execution_calls"]==0
    assert not list((tmp_path/"detection").rglob("test_*.py"))
    assert "Do not write tests" in calls[0]["system"]


def test_final_detection_call_requests_a_decision(tmp_path):
    prepared,candidate=subject(tmp_path);prepared["candidates"]=[candidate]
    calls=[]
    actions=[{"action":"inspect","query":{"kind":kind}} for kind in ("tests","scope")]+[decision()]
    result=run_detection(prepared,tmp_path/"detection",provider=provider_script(actions,calls))
    assert "Decide now" in calls[-1]["prompt"] and result["results"][0]["rounds"]==3


def test_incomplete_gap_or_generated_code_is_not_accepted(tmp_path):
    prepared,_=subject(tmp_path)
    with pytest.raises(ValueError,match="generation_and_execution_not_available"):
        parse_decision(decision()|{"tests":[]},prepared)
    with pytest.raises(ValueError,match="missing_current_behavior"):
        parse_decision(decision()|{"current_behavior":""},prepared)


def test_detection_rejects_augmentation_action_without_writing_source(tmp_path):
    prepared,candidate=subject(tmp_path);prepared["candidates"]=[candidate]
    calls=[]
    result=run_detection(prepared,tmp_path/"detection",max_rounds=1,provider=provider_script([
        {"action":"augment","tests":[{"path":"test_new.py","code":"assert False"}]}],calls))
    assert result["results"][0]["decision"]=="unknown"
    assert result["results"][0]["stop_reason"]=="action_error"
