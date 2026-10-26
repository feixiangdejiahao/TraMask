import json
from pathlib import Path
import sys

import pytest

from augmentation.agent import AGENT_SYSTEM, _execution_view, run_agent
from augmentation.distinctions import behavioral_distinction, check_generated_conditions, resolve_target
from augmentation.pipeline import parse_response, prepare
from augmentation.presentation import evidence_payload, inspect
from augmentation.ranking import rank_candidates
from test_agent import augmentation, provider_script, subject
from test_joint import DEFAULT_TS, patch


def test_path_query_searches_global_inventory_and_line_intersection(tmp_path):
    prepared, candidate = subject(tmp_path)
    other = dict(prepared["tests"][candidate["test_ids"][0]])
    other.update(id="outside", name="other", span={**other["span"], "path":"tests/other.py", "line":10, "end_line":14})
    prepared["tests"]["outside"] = other
    prepared["source_files"]["tests/other.py"] = {"code":"", "language":"python"}
    query = {"kind":"tests", "path":"tests/other.py", "start_line":12, "end_line":12}
    result = inspect(prepared, candidate, query)
    assert [t["id"] for t in result["tests"]] == ["outside"]
    assert result["query_scope"]["inventory"] == "snapshot"
    assert not inspect(prepared, candidate, query | {"start_line":15, "end_line":20})["tests"]
    response = parse_response(json.dumps({"decision":"selection_problem", "reason":"Discovered via a path query", "distinction":"Existing joint check", "tests":[], "existing_test_ids":["outside"]}), prepared, candidate["id"])
    assert response["existing_test_ids"] == ["outside"]


def test_path_query_never_falls_back_and_pages_only_matching_tests(tmp_path):
    prepared, candidate = subject(tmp_path)
    test = next(iter(prepared["tests"].values()))
    for i in range(10):
        prepared["tests"][str(i)] = {**test, "id":str(i), "span":{**test["span"], "path":"tests/x.py", "line":i+1, "end_line":i+1}}
    query = {"kind":"tests", "path":"tests"}
    one = inspect(prepared, candidate, query)
    two = inspect(prepared, candidate, query | {"offset":6})
    assert len(one["tests"]) == 6 and one["has_more"]
    assert len(two["tests"]) == 4 and not two["has_more"]
    assert not set(t["id"] for t in one["tests"]) & set(t["id"] for t in two["tests"])
    assert inspect(prepared, candidate, query | {"path":"missing.py"})["status"] == "path_not_in_snapshot"
    with pytest.raises(ValueError, match="invalid_test_query_path"):
        inspect(prepared, candidate, query | {"path":"../outside"})


def test_append_scope_rule_is_present_in_agent_and_evidence(tmp_path):
    prepared, candidate = subject(tmp_path)
    assert "adds your\ncode at the end" in AGENT_SYSTEM
    assert "legal module scope" in AGENT_SYSTEM
    assert "nested describe block" in AGENT_SYSTEM
    assert "module scope" in evidence_payload(prepared,candidate)["test_edit_context"]["append_location"]


def test_separate_calls_do_not_preserve_joint_target(tmp_path):
    prepared, candidate = subject(tmp_path)
    target = resolve_target(candidate, {"condition_values":{d["id"]:True for d in candidate["behavior"]["conditions"]}})
    response = augmentation()
    response["tests"][0]["code"] = "from lib import choose\ndef test_parts():\n assert choose(1,0)==0\n assert choose(0,1)==0\n"
    result = check_generated_conditions(prepared,candidate,response,target)
    assert result["status"] == "not_preserved"
    assert len({r["entry_call"] for r in result["rows"]}) == 2
    assert check_generated_conditions(prepared,candidate,augmentation(),target)["status"] == "source_supported"


def test_original_appended_test_cannot_supply_missing_generated_condition(tmp_path):
    prepared,candidate = subject(tmp_path)
    path=Path(prepared["repository"])/"test_lib.py"
    path.write_text("from lib import choose\ndef test_original():\n assert choose(1,1)==0\n")
    prepared=prepare(prepared["repository"],prepared["patch"],prepared["issue"])
    candidate=next(c for c in prepared["candidates"] if c["family"]=="joint_conditions")
    target=resolve_target(candidate,{"condition_values":{d["id"]:True for d in candidate["behavior"]["conditions"]}})
    response=augmentation()
    response["tests"]=[{"path":"test_lib.py","mode":"append","code":"def test_parts():\n assert choose(1,0)==0\n"}]
    result=check_generated_conditions(prepared,candidate,response,target)
    assert result["generated_test_definitions"]==1
    assert result["status"]=="not_preserved"


def test_omitted_option_is_not_replaced_by_explicit_default(tmp_path):
    (tmp_path/"lib.ts").write_text(DEFAULT_TS)
    (tmp_path/"lib.test.ts").write_text("import {parse} from './lib'; test('old',()=>{expect(parse({}, {mode:'put'})).toBe(false)});")
    prepared=prepare(tmp_path,patch("lib.ts",DEFAULT_TS),"Default put mode must still check required fields.")
    candidate=next(c for c in prepared["candidates"] if c["family"]=="default_propagation")
    target=resolve_target(candidate)
    def response(args):
        return {"tests":[{"path":"new.test.ts","mode":"new","code":f"import {{parse}} from './lib'; test('joint',()=>{{expect(parse({args})).toBe(false)}});"}]}
    assert check_generated_conditions(prepared,candidate,response("{}, {mode:'put'}"),target)["status"]=="not_preserved"
    assert check_generated_conditions(prepared,candidate,response("{}"),target)["status"]=="source_supported"
    unknown=check_generated_conditions(prepared,candidate,response("{}, externalOptions()"),target)
    assert unknown["status"]=="unknown"


def test_condition_analysis_reaches_target_after_four_forwarding_helpers(tmp_path):
    code="def choose(a,b):\n if a and b:\n  return 1\n return 0\n"
    for name,following in [("h3","choose"),("h2","h3"),("h1","h2"),("entry","h1")]:
        code+=f"def {name}(a,b):\n return {following}(a,b)\n"
    (tmp_path/"lib.py").write_text(code)
    prepared=prepare(tmp_path,patch("lib.py",code),"Both inputs must be true.")
    candidate=next(c for c in prepared["candidates"] if c["family"]=="joint_conditions")
    candidate["function_ids"]=prepared["analysis"]["changed_functions"]
    target=resolve_target(candidate,{"condition_values":{d["id"]:True for d in candidate["behavior"]["conditions"]}})
    response={"tests":[{"path":"test_new.py","mode":"new","code":"from lib import entry\ndef test_joint():\n assert entry(True,True)==1\n"}]}
    assert check_generated_conditions(prepared,candidate,response,target)["status"]=="source_supported"


def test_final_exploration_call_gets_execution_repair_opportunity(tmp_path):
    prepared,candidate=subject(tmp_path)
    broken=augmentation()
    broken["tests"][0]["code"]="from lib import choose\ndef test_joint():\n assert choose(missing_fixture,1)==1\n"
    calls=[]
    actions=[{"action":"inspect","reason":"Read code","query":{"kind":"source","path":"lib.py"}},
             {"action":"inspect","reason":"Read original test","query":{"kind":"tests"}},
             {"action":"augment","reason":"Joint input","response":broken},
             {"action":"augment","reason":"Repair the missing fixture; retain the same oracle","response":augmentation()},
             {"action":"finish","decision":"unknown","reason":"Valid failing assertion needs semantic review"}]
    result=run_agent(prepared,tmp_path/"agent",candidate_ids=[candidate["id"]],provider=provider_script(actions,calls),
                     command=[sys.executable,"-m","pytest","-q","{test_paths}"],token_budget=400000)
    assert len(calls)==5 and result["results"][0]["executions"]==2
    assert "NameError" in calls[3]["prompt"]
    prompt=json.loads(calls[3]["prompt"])
    assert prompt["remaining"]["phase"]=="feedback"
    assert prompt["active_target"]==json.loads(calls[4]["prompt"])["active_target"]
    assert "AssertionError" in calls[4]["prompt"]
    assert result["results"][0]["proposals"][-1]["condition_status"]=="source_supported"


def test_feedback_budget_is_not_spent_on_extra_exploration(tmp_path):
    prepared,candidate=subject(tmp_path)
    calls=[]
    actions=[{"action":"inspect","reason":"Read one fact","query":{"kind":kind}} for kind in ("tests","scope","requirement")]
    result=run_agent(prepared,tmp_path/"agent",candidate_ids=[candidate["id"]],provider=provider_script(actions,calls),token_budget=400000)
    assert len(calls)==3 and result["results"][0]["status"]=="unknown"


def test_target_change_requires_reason_and_does_not_erase_previous_target(tmp_path):
    prepared,candidate=subject(tmp_path)
    target=resolve_target(candidate)
    different={d["id"]:False for d in candidate["behavior"]["conditions"]}
    calls=[]
    actions=[{"action":"augment","reason":"Check joint inputs","response":augmentation()},
             {"action":"augment","reason":"Try an easier input","target":{"condition_values":different},"response":augmentation()},
             {"action":"finish","decision":"unknown","reason":"Keep the original hypothesis"}]
    result=run_agent(prepared,tmp_path/"agent",candidate_ids=[candidate["id"]],provider=provider_script(actions,calls),
                     max_rounds=1,token_budget=300000)
    prompt=json.loads(calls[2]["prompt"])
    assert "target_change_requires_reason" in calls[2]["prompt"]
    assert prompt["active_target"]["condition_values"]==target["condition_values"]
    assert result["generated_proposals"]==1


def test_condition_check_unknown_when_only_shared_identity_is_required(tmp_path):
    prepared,candidate=subject(tmp_path)
    dimension=candidate["behavior"]["conditions"][0]
    dimension.update(kind="sharing",domain=["shared","distinct"],expression="same storage")
    target=resolve_target(candidate,{"condition_values":{dimension["id"]:"shared"}})
    assert check_generated_conditions(prepared,candidate,augmentation(),target)["status"]=="unknown"


def test_feedback_prioritizes_failure_beyond_first_thirty_rows(tmp_path):
    folder=tmp_path/"augmented"
    folder.mkdir()
    tests=[{"id":str(i),"status":"skip"} for i in range(48)]+[{"id":"joint","status":"fail","detail":"ReferenceError: world is not defined"}]
    (folder/"result.json").write_text(json.dumps({"tests":tests}))
    (folder/"go.jsonl").write_text(json.dumps({"Output":"undefined: time\n"})+"\n")
    view=_execution_view({"augmented":{"status":"fail","tests":tests[:30]}},tmp_path)["augmented"]
    assert view["tests"][0]["id"]=="joint"
    assert view["test_results_total"]==49 and view["test_results_truncated"]
    assert "undefined: time" in view["structured_output_tail"]


def test_ranking_prefers_source_effect_and_preserves_distinct_conditions(tmp_path):
    prepared,candidate=subject(tmp_path)
    import copy
    unrelated=copy.deepcopy(candidate)
    unrelated["id"]="unrelated"
    unrelated["behavior"]["conditions"]=[]
    for n in unrelated["behavior"]["operations"]:
        n["changed"]=False
        n["code"]="unrelated_operation()"
    ranked,receipt=rank_candidates([unrelated,candidate],"choose both positive inputs",limit=2)
    assert ranked[0]["id"]==candidate["id"]
    assert receipt[0]["components"]["changed_source"]>0
    assert len(ranked)==2


def test_distinction_retains_source_conditions_and_observation(tmp_path):
    prepared,candidate=subject(tmp_path)
    view=behavioral_distinction(candidate)
    assert view["targets"] and view["conditions"] and view["operations"]
    assert any(n["code"].startswith("return") for n in view["observation_points"])
    assert all(d["span"]["path"]=="lib.py" for d in view["conditions"])
    effects=view["targets"][0]["predicted_branch_effects"]
    assert any(e["code"]=="return 0" and e["branch_condition"]=="enabled" for e in effects)
