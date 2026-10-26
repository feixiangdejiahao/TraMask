"""Uninstrumented P/Q controls, separated from observational probe work.

The six controls are the original half of a three-repeat four-variant
qualification. No scientific label is inferred from shell status or summaries.
"""
from pathlib import Path

from tramask_pilot.corpus import read, receipt
from tramask_pilot.fidelity import test_evidence
from tramask_pilot.submission_replay import ENV
from .runtime import execute_variant
from .study import RUN, now, sha, write_new
from .workflow_primary_v02 import public_packet
from .variants import _apply


def prepare(case, technical_review, run=RUN):
    run = Path(run)
    directory = run / "runs" / case["id"]
    fixed_binding = read(directory / "reserved_fixed_reference.json")["fixed_counterfactual"]
    if receipt(fixed_binding["path"]) != fixed_binding:
        raise ValueError("Fixed reserved reference changed")
    fixed_path = Path(fixed_binding["path"])
    fixed = read(fixed_path)
    selected = read(directory / "selection.json")
    packet = public_packet(case, run)
    files = {**packet["final_sources"], **packet["selected_test"]["files"]}
    if fixed["original_command"] != selected["command"]:
        raise ValueError("Original command binding changed")
    q = _apply(files, fixed["alternative"]["edits"])
    tests = set(packet["selected_test"]["files"])
    if any(q[p] != files[p] for p in tests):
        raise ValueError("Q changed original test")
    capsules = {}
    capsule = directory / "historical_test_capsule.json"
    if capsule.exists():
        recovery = read(capsule)
        if recovery.get("approved_for_explicit_harness_materialization") is not True:
            raise ValueError("Historical capsule not qualified")
        capsules = {path.lstrip("/"): row for path, row in recovery["files"].items()}
        if any(files[p] != row["content"] or sha(files[p]) != row["sha256"] for p, row in capsules.items()):
            raise ValueError("Capsule content mismatch")
    specs = {}
    for name, version in (("p_original", files), ("q_original", q)):
        specs[name] = {}
        for path, content in version.items():
            if path in capsules:
                specs[name]["/" + path] = {"content": content, "new_file": True}
            elif content != files[path]:
                specs[name]["/" + path] = {"content": content, "before_sha256": sha(files[path])}
    if technical_review.get("approved_for_control_execution") is not True:
        raise ValueError("Explicit technical review required")
    command = technical_review["effective_command"]
    if command != fixed["original_command"]:
        from .cache_qualification import cache_bypass_command
        allowed = []
        try:
            allowed.append(cache_bypass_command(fixed["original_command"]))
        except ValueError:
            pass
        if selected.get("runner_contract"):
            bound = selected["runner_contract"]
            if receipt(bound["path"]) != bound:
                raise ValueError("Runner contract changed")
            allowed.append(read(bound["path"])["execution_command_with_explicit_transport"])
        runner_plan = directory / "runner_qualification_v01/plan.json"
        if runner_plan.exists():
            allowed.append(read(runner_plan)["effective_command"])
        if command not in allowed:
            raise ValueError("Command lacks an exact runner qualification contract")
    plan = {"case_id": case["id"], "created_at": now(), "checkpoint": case["checkpoint"],
            "fixed_counterfactual": receipt(fixed_path), "selection": receipt(directory / "selection.json"),
            "source_sha256": {path: sha(text) for path, text in files.items()},
            "original_command": fixed["original_command"], "effective_command": command,
            "working_directory": selected["working_directory"], "test_timeout_seconds": case["test_timeout_seconds"],
            "resources": case["resources"], "environment": ENV, "variants": specs,
            "build_commands": technical_review.get("build_commands", []),
            "generated_runtime": technical_review.get("generated_runtime", False),
            "production_paths": sorted({"/" + e["path"] for e in fixed["alternative"]["edits"]}),
            "observation_paths": selected.get("observation_paths", []), "repeats": 3,
            "technical_review": technical_review, "scientific_label": None,
            "interpretation": "Six uninstrumented controls only; probe execution and E2-E5 qualification remain separate. Test failures remain observations, never masking votes.",
            "implementation": [receipt(Path(__file__)), receipt(Path(__file__).with_name("runtime.py"))]}
    write_new(directory / "original_pair_controls_v02/plan.json", plan)
    return plan


def execute(case_id, run=RUN):
    out = Path(run) / "runs" / case_id / "original_pair_controls_v02"
    plan = read(out / "plan.json")
    for bound in plan["implementation"] + [plan["fixed_counterfactual"], plan["selection"]]:
        if receipt(bound["path"]) != bound:
            raise ValueError("Frozen original-pair input or implementation changed")
    if (out / "summary.json").exists():
        summary = read(out / "summary.json")
        for bound in summary["receipts"]:
            if receipt(bound["path"]) != bound:
                raise ValueError("Completed original-pair receipt changed")
        return summary
    records = []
    for repeat in range(1, plan["repeats"] + 1):
        for variant, files in plan["variants"].items():
            destination = out / f"repeat_{repeat:02d}" / variant
            if destination.exists():
                raise FileExistsError("Partial control execution retained; no implicit redispatch")
            result = execute_variant(plan["checkpoint"], destination, plan["effective_command"], plan["test_timeout_seconds"],
                files=files, observation_paths=plan["observation_paths"], build_commands=plan["build_commands"],
                env=plan["environment"], workdir=plan["working_directory"], resources=plan["resources"],
                production_paths=plan["production_paths"], generated_runtime=plan["generated_runtime"])
            execution = result.get("execution") or {}
            text = execution.get("stdout", "") + "\n" + execution.get("stderr", "")
            records.append({"repeat": repeat, "variant": variant, "result": receipt(destination / "result.json"),
                "status": result.get("status"), "returncode": execution.get("returncode"),
                "timed_out": execution.get("timed_out"), "runner_text_facts": test_evidence(text),
                "elapsed_seconds": execution.get("elapsed_seconds")})
    receipts = [receipt(path) for path in sorted(out.rglob("*")) if path.is_file()]
    summary = {"case_id": case_id, "completed_at": now(), "plan": receipt(out / "plan.json"),
               "runs": records, "subject_command_executions": len(records), "receipts": receipts,
               "scientific_label": None, "status": "controls_executed_pending_measurement_and_semantic_review"}
    write_new(out / "summary.json", summary)
    return summary
