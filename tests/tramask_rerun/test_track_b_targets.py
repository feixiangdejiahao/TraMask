"""Exact proposal staging and mocked scheduling; never launch subjects."""
import copy
import json

import pytest

from test_validation_material import evidence, save, sha
from tramask_rerun import track_b_targets as targets


def proposal(material):
    return {"status": "proposed", "selected_test_id": material["test_id"], "original_command": material["command"],
        "alternative": {"edits": [{"path": "app/code.py", "old": "return 1", "new": "return 2"}]},
        "instrumentation": {"common_edits": [], "p_edits": [], "q_edits": [], "helper_files": [],
                            "command": material["command"], "shared_anchors": [{"id": "declared_only", "channel": "effect"}]}}


def prepare(evidence, tmp_path, edit=None, policy=None):
    material = evidence.load(); p = proposal(material)
    if edit:
        edit(p, material)
    receipt = save(tmp_path / "planning.json", p)
    case = {"id": "H001", "checkpoint": evidence.checkpoint, "test_timeout_seconds": 5, "resources": {"cpus": 1}}
    return targets.prepare_target(material, receipt, case, runner_policy_receipt=policy), material, p


def test_exact_historical_material_common_arm_edits_and_new_helpers(evidence, tmp_path):
    evidence.test["files"]["tmp/test.py"] = "assert value() == 0\n"; evidence.rebind()
    def change(p, m):
        p["instrumentation"].update(
            common_edits=[{"path": "tmp/test.py", "old": "assert value() == 0", "new": "print('common')\nassert value() == 0"}],
            p_edits=[{"path": "tmp/probe/helper.py", "old": "# helper", "new": "# helper P"}],
            q_edits=[{"path": "app/code.py", "old": "return 2", "new": "print('Q')\n    return 2"}],
            helper_files=[{"path": "tmp/probe/helper.py", "content": "# helper\n"}],
            command="python -u /tmp/test.py; echo ${PIPESTATUS[0]}")
    plan, m, p = prepare(evidence, tmp_path, change)
    assert not plan["staging_failures"]
    assert plan["proposal"] == p
    for name in targets.ARMS:
        arm = plan["arms"][name]
        assert arm["files"]["/tmp/test.py"]["before_sha256"] == sha(evidence.native["tmp/test.py"])
        assert "assert value() == 0" in arm["full_text"]["tmp/test.py"]
    assert plan["arms"]["p_instrumented"]["files"]["/tmp/probe/helper.py"]["new_file"] is True
    assert plan["arms"]["p_instrumented"]["full_text"]["tmp/probe/helper.py"] == "# helper P\n"
    assert plan["arms"]["q_instrumented"]["command"] == "python -u /tmp/test.py; echo ${PIPESTATUS[0]}"
    assert m["test_files"]["tmp/test.py"] == "assert value() == 0\n"


def test_helper_existing_in_manifest_fails_probes_only(evidence, tmp_path):
    evidence.manifest["files"].append({"path": "/tmp/occupied.py", "kind": "file", "sha256": "0" * 64})
    plan, _, _ = prepare(evidence, tmp_path, lambda p, m: p["instrumentation"].update(
        helper_files=[{"path": "tmp/occupied.py", "content": "x = 1\n"}]))
    assert plan["arms"]["p_original"]["status"] == "prepared"
    assert plan["arms"]["q_original"]["status"] == "prepared"
    assert all(plan["arms"][n]["status"] == "staging_failure" for n in ("p_instrumented", "q_instrumented"))


def test_bad_probe_anchor_is_not_repaired_and_other_arms_survive(evidence, tmp_path):
    plan, _, _ = prepare(evidence, tmp_path, lambda p, m: p["instrumentation"].update(
        p_edits=[{"path": "app/code.py", "old": "not actually present", "new": "invented"}]))
    assert plan["arms"]["p_instrumented"]["status"] == "staging_failure"
    assert plan["arms"]["q_instrumented"]["status"] == "prepared"
    assert "exactly_once" in plan["arms"]["p_instrumented"]["reason"]


def test_invalid_q_preserves_original_p_and_records_two_q_failures(evidence, tmp_path):
    plan, _, _ = prepare(evidence, tmp_path, lambda p, m: p["alternative"]["edits"][0].update(old="missing"))
    assert {n for n, a in plan["arms"].items() if a["status"] == "prepared"} == {"p_original", "p_instrumented"}
    assert len(plan["staging_failures"]) == 2


def test_semantically_unhelpful_q_and_unused_helper_are_preserved(evidence, tmp_path):
    def edit(p, m):
        p["alternative"]["edits"][0]["new"] = "return 1  # unchanged value"
        p["instrumentation"]["helper_files"] = [{"path": "tmp/unused.py", "content": "print('not imported')\n"}]
    plan, _, p = prepare(evidence, tmp_path, edit)
    assert not plan["staging_failures"]
    assert plan["arms"]["q_original"]["full_text"]["app/code.py"].endswith("return 1  # unchanged value\n")
    assert plan["arms"]["p_instrumented"]["command"] == p["original_command"]
    assert "unused.py" not in plan["arms"]["p_instrumented"]["full_text"]["tmp/test.py"]


def test_inline_probe_uses_unique_original_body_in_supplied_command(evidence, tmp_path):
    evidence.inline("print(1)")
    def edit(p, m):
        p["instrumentation"].update(command='python -c "print(1)" | cat', common_edits=[
            {"path": m["inline"]["path"], "old": "print(1)", "new": "print(2)"}])
    plan, m, _ = prepare(evidence, tmp_path, edit)
    assert plan["arms"]["p_instrumented"]["command"] == 'python -c "print(2)" | cat'
    assert "/" + m["inline"]["path"] not in plan["arms"]["p_instrumented"]["files"]


def test_inline_missing_body_and_quote_collision_are_staging_failures(evidence, tmp_path):
    evidence.inline("print(1)")
    plan, _, _ = prepare(evidence, tmp_path, lambda p, m: p["instrumentation"].update(command="python /tmp/helper.py"))
    assert "unique_original_inline_body" in plan["arms"]["p_instrumented"]["reason"]
    plan, _, _ = prepare(evidence, tmp_path, lambda p, m: p["instrumentation"].update(common_edits=[
        {"path": m["inline"]["path"], "old": "print(1)", "new": 'print("unsafe")'}]))
    assert "collision" in plan["arms"]["p_instrumented"]["reason"]


@pytest.mark.parametrize("kind,command,expected", [
    ("go_cache_bypass", "go test -v . | tail -2", 'export GOFLAGS="${GOFLAGS-$(go env GOFLAGS)} -count=1"\n'),
    ("jest_worker_cap", "npx jest test/example.js | tail -2", "npx jest --maxWorkers=2 test/example.js | tail -2"),
])
def test_explicit_runner_policy_is_shared_without_changing_pipeline(evidence, tmp_path, kind, command, expected):
    evidence.test["command"] = command; evidence.rebind()
    qualification = save(tmp_path / "runner_review.json", {"qualified": True})
    policy = save(tmp_path / "policy.json", {"kind": kind, "max_workers": 2, "approved_for_execution": True,
        "shared_across_all_arms": True, "qualification_receipt": qualification})
    plan, _, _ = prepare(evidence, tmp_path, policy=policy)
    commands = {a["command"] for a in plan["arms"].values()}
    assert commands == {expected + command if kind == "go_cache_bypass" else expected}


def fake_executor(calls, channels=True):
    def run(plan, arm, directory):
        directory.mkdir(parents=True)
        calls.append((str(directory), copy.deepcopy(arm["files"])))
        events = []
        if channels and directory.name.endswith("instrumented"):
            events = [{"channel": c, "anchor": c, "target_reached": True, "value": 1,
                       "test": "case", "input": "input"} for c in ("effect", "observation")]
        text = "".join("TRAMASK_EVENT " + json.dumps(e) + "\n" for e in events)
        execution = {"status": "completed", "returncode": 0, "timed_out": False}
        for name, value in (("stdout", text), ("stderr", "")):
            path = directory / (name + ".raw"); path.write_bytes(value.encode())
            execution.update({"raw_" + name: str(path), name + "_sha256": sha(value), name + "_bytes": len(value.encode())})
        result = {"status": "completed", "execution": execution, "observations": []}
        save(directory / "result.json", result)
        return result
    return run


def test_exactly_twelve_isolated_runs_remain_pending_semantic_audit(evidence, tmp_path, monkeypatch):
    plan, _, _ = prepare(evidence, tmp_path); frozen = targets.write_preparation(plan, tmp_path / "prepared.json")
    calls = []; monkeypatch.setattr(targets, "_execute_arm", fake_executor(calls))
    summary = targets.execute_preparation(frozen, tmp_path / "execution")
    assert len(calls) == 12 and len({p for p, _ in calls}) == 12
    assert summary["subject_command_executions"] == 12 and summary["qualified_for_stage2"] is False
    pending = json.loads((tmp_path / "execution/qualification_pending.json").read_text())
    assert pending["actual_both_channels_every_instrumented_repeat"] is True
    assert pending["semantic_identity_qualified"] is None and pending["noninterference_qualified"] is None
    assert not (tmp_path / "execution/qualification.json").exists()
    with pytest.raises(FileExistsError, match="no_redispatch"):
        targets.execute_preparation(frozen, tmp_path / "execution")
    assert len(calls) == 12


def test_missing_actual_markers_not_filled_from_declared_anchors(evidence, tmp_path, monkeypatch):
    plan, _, _ = prepare(evidence, tmp_path); frozen = targets.write_preparation(plan, tmp_path / "prepared.json")
    monkeypatch.setattr(targets, "_execute_arm", fake_executor([], channels=False))
    targets.execute_preparation(frozen, tmp_path / "execution")
    pending = json.loads((tmp_path / "execution/qualification_pending.json").read_text())
    assert pending["status"] == "measurement_unusable_pending_audit"
    assert pending["actual_both_channels_every_instrumented_repeat"] is False


def test_partial_outputs_and_mutated_plans_never_dispatch(evidence, tmp_path, monkeypatch):
    plan, _, _ = prepare(evidence, tmp_path); frozen = targets.write_preparation(plan, tmp_path / "prepared.json")
    calls = []; monkeypatch.setattr(targets, "_execute_arm", fake_executor(calls))
    (tmp_path / "partial").mkdir()
    with pytest.raises(FileExistsError):
        targets.execute_preparation(frozen, tmp_path / "partial")
    assert not calls
    plan["arms"]["p_original"]["command"] = "echo repaired"
    with pytest.raises(ValueError, match="plan_changed"):
        targets.write_preparation(plan, tmp_path / "changed.json")


def test_build_and_binary_hash_precede_test_in_same_mock_clone(evidence, tmp_path, monkeypatch):
    evidence.test["build_contract"] = {"required_before_execution": True,
        "exact_original_build_command": "go build -o /tmp/ytt ./cmd/ytt", "working_directory": "/app", "expected_binary_path": "/tmp/ytt"}
    plan, _, _ = prepare(evidence, tmp_path); order = []
    class Container:
        def __init__(self, *a, **k): pass
        def __enter__(self): order.append("clone"); return self
        def __exit__(self, *a): order.append("close")
    def control(container, program, payload, out):
        kind = "writes" if payload.get("operation") == "write" else "binary_hash"
        order.append(kind)
        return {"status": "complete", "sha256": "1" * 64, "path": payload.get("path"), "bytes": 1, "mode": 0o755}
    def run(container, command, timeout, out, env, cwd):
        order.append("build" if command.startswith("go build") else "test")
        return {"status": "completed", "returncode": 0, "stdout": "", "stderr": ""}
    monkeypatch.setattr(targets.runtime, "Container", Container)
    monkeypatch.setattr(targets.runtime, "_control_json", control)
    monkeypatch.setattr(targets.runtime, "_run", run)
    result = targets._execute_arm(plan, plan["arms"]["p_original"], tmp_path / "arm")
    assert order == ["clone", "writes", "build", "binary_hash", "test", "close"]
    assert result["builds"][0]["fresh_binary_receipt"]["sha256"] == "1" * 64
    order.clear()
    def no_binary(container, program, payload, out):
        if payload.get("operation") == "write":
            order.append("writes"); return {"status": "complete"}
        order.append("binary_hash"); return {"status": "error", "reason": "missing_binary"}
    monkeypatch.setattr(targets.runtime, "_control_json", no_binary)
    failed = targets._execute_arm(plan, plan["arms"]["p_original"], tmp_path / "failed_arm")
    assert order == ["clone", "writes", "build", "binary_hash", "close"]
    assert failed["status"] == "build_binary_receipt_failed" and failed["execution"] is None
