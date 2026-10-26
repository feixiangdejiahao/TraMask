import json
from pathlib import Path
import sys

from augmentation.agent import run_agent
from augmentation.execution import execute
from augmentation.pipeline import prepare


def subject(tmp_path):
    root = tmp_path / "subject"
    root.mkdir()
    code = "def choose(a, b):\n if a > 0 and b > 0:\n  return 0\n return 0\n"
    (root / "lib.py").write_text(code)
    (root / "test_lib.py").write_text("from lib import choose\ndef test_original():\n assert choose(1, 0) == 0\n")
    patch = "--- a/lib.py\n+++ b/lib.py\n@@ -1 +1,4 @@\n" + "\n".join("+"+s for s in code.splitlines())
    prepared = prepare(root, patch, "Return one exactly when both inputs are positive.")
    candidate = next(c for c in prepared["candidates"] if c["family"] == "joint_conditions")
    return prepared, candidate


def provider_script(actions, calls):
    def provider(request, output, *, root):
        calls.append(request)
        output.mkdir()
        (output / "completion.txt").write_text(json.dumps(actions[len(calls)-1]))
        return {"status":"complete", "external_model_calls":0, "usage":{"prompt_tokens":100, "completion_tokens":11, "total_tokens":111}}
    return provider


def augmentation():
    return {"decision":"gap", "reason":"The public requirement requires both positive inputs.",
            "distinction":"Jointly positive inputs must return one.", "existing_test_ids":[],
            "tests":[{"path":"test_joint.py", "mode":"new", "code":"from lib import choose\ndef test_joint():\n assert choose(1,1) == 1\n"}]}


def test_agent_queries_then_generates_and_receives_actual_failure(tmp_path):
    prepared, candidate = subject(tmp_path)
    calls = []
    actions = [{"action":"inspect", "reason":"Read the implementation", "query":{"kind":"source", "path":"lib.py"}},
               {"action":"augment", "reason":"Check the joint condition", "response":augmentation()},
               {"action":"finish", "decision":"unknown", "reason":"Failure needs semantic review", "distinction":"Both positive inputs"}]
    result = run_agent(prepared, tmp_path / "agent", candidate_ids=[candidate["id"]], provider=provider_script(actions,calls),
                       command=[sys.executable,"-m","pytest","-q","{test_paths}"], token_budget=200000)
    assert len(calls) == 3 and result["charged_tokens"] == 333
    assert result["generated_proposals"] == 1 and result["confirmed_bug_count"] is None
    final_prompt = json.loads(calls[-1]["prompt"])
    feedback = final_prompt["actions_and_feedback"][-1]["feedback"]
    assert feedback["augmented"]["returncode"] != 0
    assert feedback["augmented"]["activation"]["status"] == "observed"
    assert feedback["baseline"]["status"] == "baseline_not_requested"
    assert not (Path(prepared["repository"]) / "test_joint.py").exists()


def test_agent_budget_prevents_provider_call_and_keeps_unknown(tmp_path):
    prepared, candidate = subject(tmp_path)
    calls=[]
    result=run_agent(prepared,tmp_path/"agent",candidate_ids=[candidate["id"]],provider=provider_script([],calls),token_budget=10)
    assert not calls
    assert result["results"][0]["status"] == "unknown"
    assert result["results"][0]["stop_reason"] == "total_token_budget"


def test_repeated_query_stops_without_promoting_to_no_gap(tmp_path):
    prepared,candidate=subject(tmp_path)
    calls=[]
    action={"action":"inspect","reason":"Read source","query":{"kind":"source","path":"lib.py"}}
    result=run_agent(prepared,tmp_path/"agent",candidate_ids=[candidate["id"]],provider=provider_script([action,action],calls),token_budget=200000)
    assert len(calls)==2
    assert result["results"][0]["stop_reason"]=="repeated_action_without_new_evidence"
    assert result["results"][0]["status"]=="unknown"


def test_inspection_cannot_read_files_outside_prepared_sources(tmp_path):
    prepared,candidate=subject(tmp_path)
    (Path(prepared["repository"])/".env").write_text("TOP_SECRET")
    calls=[]
    actions=[{"action":"inspect","reason":"Read missing source","query":{"kind":"source","path":".env"}},
             {"action":"finish","decision":"unknown","reason":"Missing evidence"}]
    run_agent(prepared,tmp_path/"agent",candidate_ids=[candidate["id"]],provider=provider_script(actions,calls),token_budget=200000)
    assert "TOP_SECRET" not in json.dumps(calls)
    assert "source_not_in_prepared_snapshot" in calls[-1]["prompt"]


def test_runtime_conditions_retain_separate_invocations(tmp_path):
    prepared,candidate=subject(tmp_path)
    row=augmentation() | {"candidate_id":candidate["id"]}
    row["tests"][0]["code"]="from lib import choose\ndef test_separate():\n assert choose(1,0)==0\n assert choose(0,1)==0\n"
    result=execute(prepared,row,tmp_path/"execution",[sys.executable,"-m","pytest","-q","{test_paths}"],run_baseline=False)
    trace=result["augmented"]["activation"]
    assert result["augmented"]["returncode"]==0
    assert trace["processes_finished"]
    entries={e["entry"] for e in trace["events"] if e["function"]=="choose"}
    assert len(entries)==2
    evaluated=[e["condition_result"]["value"] for e in trace["events"] if e.get("condition_result",{}).get("known")]
    assert False in evaluated and True in evaluated


def test_runtime_does_not_merge_identical_nested_calls(tmp_path):
    root = tmp_path / "subject"
    root.mkdir()
    code = "def choose(a, b):\n if a and b:\n  return 1\n return 0\ndef entry(a, b):\n choose(a, b)\n return choose(a, b)\n"
    (root / "lib.py").write_text(code)
    patch = "--- a/lib.py\n+++ b/lib.py\n@@ -1 +1,7 @@\n" + "\n".join("+" + s for s in code.splitlines())
    prepared = prepare(root, patch, "Return one when both inputs are true.")
    candidate = next(c for c in prepared["candidates"] if c["family"] == "joint_conditions")
    # Include the entry source operation in this local probe, as an agent can
    # do by choosing a behavior that spans caller and callee.
    extra = next(n for n in prepared["relation_index"]["nodes"].values() if n["code"] == "return choose(a, b)")
    candidate["behavior"]["operations"].append(extra)
    response = augmentation() | {"candidate_id": candidate["id"]}
    response["tests"][0]["code"] = "from lib import entry\ndef test_repeat():\n assert entry(1,1) == 1\n"
    result = execute(prepared, response, tmp_path / "execution", [sys.executable, "-m", "pytest", "-q", "{test_paths}"], run_baseline=False)
    events = [e for e in result["augmented"]["activation"]["events"] if e["function"] == "choose"]
    assert len({e["entry"] for e in events}) == 1
    assert len({e["invocation"] for e in events}) == 2
