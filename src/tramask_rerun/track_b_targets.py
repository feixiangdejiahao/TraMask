"""Exact stage1 Track B target preparation and bounded four-arm execution.

No reference/P1 counterfactual is consulted. Preparation is pure: proposed Q,
common/P/Q probes, helpers and commands are preserved without semantic repairs.
``prepare_registered_cell`` binds one of the eight registered stage1 outputs;
``write_preparation`` freezes it; only an explicit ``execute_preparation`` call
runs subjects. The runner never writes stage2's ``qualification.json``: actual
channels, semantic identity and noninterference still require technical audit.

Usage (execution is explicit)::

    plan = prepare_registered_cell(case, "M4", 1, run,
        runner_policy_receipt=optional_qualified_runner_policy)
    bound = write_preparation(plan, cell / "target_preparation_v01.json")
    summary = execute_preparation(bound, cell / "target_execution")

Freeze this module before preparing durable plans. Runtime output directories
must be new. A structural failure in one arm remains in every repeat's records;
other independently stageable arms still run. These are method measurements,
not repaired or semantically qualified probes.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path, PurePosixPath
import re

from tramask_pilot.submission_replay import ENV
from . import paired, runtime, variants
from .cache_qualification import cache_bypass_command
from .validation_material import (_checkpoint, _digest, _read, _replace_inline,
                                  _sha, _shell_quotes, load_validation_material,
                                  plan_validation)


CELLS = (("HF005", "M4", 1), ("HF010", "M3", 1), ("HF010", "M3", 2),
         ("HF010", "M4", 1), ("HF012", "M4", 2), ("HS003", "M3", 1),
         ("HS004", "M4", 1), ("HS004", "M4", 2))
ARMS = ("p_original", "q_original", "p_instrumented", "q_instrumented")


def _receipt(path):
    return paired._receipt(paired._output(path))


def _implementation():
    return [_receipt(path) for path in (Path(__file__), Path(variants.__file__), Path(runtime.__file__),
        Path(paired.__file__), Path(__file__).with_name("validation_material.py"),
        Path(__file__).with_name("cache_qualification.py"), Path(__file__).with_name("evidence.py"))]


def _runner_command(command, policy):
    if policy is None:
        return command
    if policy.get("approved_for_execution") is not True or policy.get("shared_across_all_arms") is not True:
        raise ValueError("explicit_shared_runner_policy_required")
    _read(policy["qualification_receipt"], json_value=False)
    if policy.get("kind") == "go_cache_bypass":
        if not re.search(r"\bgo\s+test\b", command):
            raise ValueError("cache_policy_requires_go_test")
        return cache_bypass_command(command)
    if policy.get("kind") == "jest_worker_cap" and policy.get("max_workers") == 2:
        if re.search(r"--(?:maxWorkers|runInBand)\b", command):
            raise ValueError("worker_policy_cannot_override_explicit_flags")
        match = re.match(r"(?:cd\s+/(?:app|tmp)\s*&&\s*)?(?:[A-Za-z_]\w*=[^\s;&|]+\s+)*(?:npx\s+)?jest(?=\s|$)", command)
        if match is None:
            raise ValueError("worker_policy_requires_one_exact_jest_runner")
        end = match.end()
        return command[:end] + " --maxWorkers=2" + command[end:]
    raise ValueError("unregistered_runner_policy")


def _helpers(proposal, material, manifest):
    rows = proposal["instrumentation"]["helper_files"]
    if not isinstance(rows, list):
        raise ValueError("helper_files_must_be_list")
    helpers = {}
    known = {row["path"]: row for row in manifest["files"]}
    for row in rows:
        if not isinstance(row, dict) or set(row) != {"path", "content"}:
            raise ValueError("helper_requires_exact_path_content")
        path = variants._path(row["path"])
        if path in helpers or "/" + path in known or path in material["terminal_files"] or path in material["test_files"]:
            raise ValueError("helper_requires_proven_new_path")
        if material["inline"] and path == material["inline"]["path"]:
            raise ValueError("helper_collides_with_inline_virtual_test")
        if not any(("/" + path).startswith(root.rstrip("/") + "/") for root in manifest.get("roots", [])):
            raise ValueError("helper_absence_not_covered_by_manifest")
        for ancestor in PurePosixPath("/" + path).parents:
            if str(ancestor) in known and known[str(ancestor)].get("kind") not in {"directory", "dir"}:
                raise ValueError("helper_has_nondirectory_ancestor")
        helpers.update(variants._files({path: row["content"]}))
    variants._collisions(set(material["terminal_files"]) | set(material["test_files"]) | set(helpers))
    return helpers


def _specs(full, material, helpers):
    result = {}
    for path, text in full.items():
        if material["inline"] and path == material["inline"]["path"]:
            continue
        before = material["predecessors"].get(path)
        if path not in material["predecessors"] and path in material["terminal_files"]:
            before = _sha(material["terminal_files"][path])
        if before is None:
            if path not in material["predecessors"] and path not in helpers:
                raise ValueError("unbound_new_probe_file")
            result["/" + path] = {"content": text, "new_file": True}
        elif _sha(text) != before:
            result["/" + path] = {"content": text, "before_sha256": before}
    runtime._file_specs(result)
    return result


def _instrumented_command(command, full, material):
    _shell_quotes(command)
    if not material["inline"]:
        return command
    inline = material["inline"]; original = inline["text"]
    if command.count(original) != 1:
        raise ValueError("instrumented_command_requires_unique_original_inline_body")
    start = len(command[:command.index(original)].encode())
    mapped = {**inline, "command_mapping": {"original_command": command,
              "script_start_byte": start, "script_end_byte": start + len(original.encode())}}
    return _replace_inline(command, mapped, full[inline["path"]])


def _bound_manifest(material):
    proofs = []
    for bound in material["authorities"]:
        try:
            value = _read(bound)
        except (ValueError, UnicodeError):
            continue
        if isinstance(value, dict) and value.get("state_validation_passed") is True and "inventory" in value:
            if _checkpoint(value.get("checkpoint")) == material["checkpoint"] and value["inventory"] in material["authorities"]:
                proofs.append(value)
    if len(proofs) != 1:
        raise ValueError("one_bound_checkpoint_proof_required")
    return _read(proofs[0]["inventory"])


def prepare_target(material, planning_receipt, case, *, runner_policy_receipt=None):
    """Pure four-arm plan; independently retain each structural staging failure.

    Optional runner policy JSON explicitly approves a shared ``go_cache_bypass``
    or ``jest_worker_cap`` (2 workers), with a bound qualification receipt.
    No runner adaptation is inferred from a case name or an execution failure.
    """
    proposal = _read(planning_receipt)
    if proposal.get("status") != "proposed" or proposal.get("selected_test_id") != material["test_id"]:
        raise ValueError("stage1_proposal_selection_mismatch")
    if proposal.get("original_command") != material["command"] or case["id"] != material["case_id"]:
        raise ValueError("stage1_original_command_or_case_mismatch")
    if _checkpoint(case["checkpoint"]) != material["checkpoint"]:
        raise ValueError("case_checkpoint_mismatch")
    timeout = runtime._timeout(case["test_timeout_seconds"])
    policy = _read(runner_policy_receipt) if runner_policy_receipt else None
    manifest = _bound_manifest(material)
    records = {}; staging_failures = []
    def failed(name, error):
        row = {"status": "staging_failure", "error_type": type(error).__name__, "reason": str(error)}
        records[name] = row; staging_failures.append({"arm": name, **row})
    base = plan_validation(material)["arms"]["p_original"]
    originals = {"p_original": base}
    try:
        originals["q_original"] = plan_validation(material, fixed_q_receipt=planning_receipt,
            frozen_output_receipt=planning_receipt)["arms"]["q_original"]
    except (ValueError, TypeError, KeyError) as error:
        failed("q_original", error)
    for name, arm in originals.items():
        try:
            records[name] = {**copy.deepcopy(arm), "status": "prepared", "proposed_command": material["command"],
                             "command": _runner_command(material["command"], policy), "explicit_new_helpers": []}
        except (ValueError, TypeError, KeyError) as error:
            failed(name, error)
    for prefix in ("p", "q"):
        name = prefix + "_instrumented"
        if prefix + "_original" not in originals:
            failed(name, ValueError("Q_staging_failed; original_proposal_not_repaired")); continue
        try:
            helpers = _helpers(proposal, material, manifest)
            source = originals[prefix + "_original"]["full_text"]
            probe = proposal["instrumentation"]
            full = variants._apply(source, probe["common_edits"])
            full.update(helpers)
            full = variants._apply(full, probe[prefix + "_edits"])
            command = _instrumented_command(probe["command"], full, material)
            records[name] = {**copy.deepcopy(originals[prefix + "_original"]), "status": "prepared",
                "full_text": full, "files": _specs(full, material, helpers), "proposed_command": probe["command"],
                "mapped_command_before_runner_policy": command, "command": _runner_command(command, policy),
                "explicit_new_helpers": sorted("/" + p for p in helpers),
                "after_sha256": {"/" + p: _sha(t) for p, t in full.items() if not material["inline"] or p != material["inline"]["path"]}}
        except (ValueError, TypeError, KeyError) as error:
            failed(name, error)
    observations = ["/" + variants._path(p) for p in proposal["instrumentation"].get("observation_paths", [])]
    plan = {"version": "track-b-target-plan.v1", "case_id": case["id"], "test_id": material["test_id"],
            "checkpoint": material["checkpoint"], "test_timeout_seconds": timeout,
            "resources": copy.deepcopy(case.get("resources", {})), "environment": copy.deepcopy(ENV),
            "repeats": 3, "max_target_executions": 12, "arms": {name: records[name] for name in ARMS},
            "planning_receipt": copy.deepcopy(planning_receipt), "proposal": proposal,
            "material_integrity_sha256": material["integrity_sha256"], "material_authorities": material["authorities"],
            "runner_policy_receipt": copy.deepcopy(runner_policy_receipt), "runner_policy": policy,
            "observation_paths": observations, "staging_failures": staging_failures,
            "implementation": _implementation(), "subject_execution_performed": False,
            "semantic_repair_performed": False, "syntax_repaired": False,
            "qualification": "pending_actual_channels_and_independent_technical_audit"}
    plan["plan_sha256"] = _digest(plan)
    return plan


def prepare_registered_cell(case, method, repeat, run, *, runner_policy_receipt=None):
    """Load only the cell's stage1 output and qualified version inventory."""
    if (case["id"], method, repeat) not in CELLS:
        raise ValueError("unregistered_target_execution_cell")
    directory = Path(run) / "runs" / case["id"]
    stage = directory / "track_b" / method / f"repeat_{repeat:02d}" / "stage_01"
    result_receipt = _receipt(stage / "result.json"); result = _read(result_receipt)
    if result.get("status") != "planning_requires_Q_execution_qualification":
        raise ValueError("stage1_not_registered_for_Q_execution")
    planning_receipt = _receipt(stage / "planning.json")
    public_receipt = result.get("public_input") or _receipt(stage / "public_input.json")
    if result.get("planning") != planning_receipt or Path(public_receipt["path"]) != (stage / "public_input.json").resolve():
        raise ValueError("frozen_stage1_result_receipt_mismatch")
    inventory = directory / ("qualified_validation_inventory_v02.json" if case["id"] == "HF005" else "qualified_validation_inventory.json")
    material = load_validation_material(public_receipt, _receipt(inventory), _read(planning_receipt)["selected_test_id"],
        checkpoint_proof_receipt=_receipt(directory / "submission_replay_v01/summary.json"),
        terminal_export_receipts=[_receipt(directory / "terminal_sources/result.json")])
    plan = prepare_target(material, planning_receipt, case, runner_policy_receipt=runner_policy_receipt)
    plan.pop("plan_sha256"); plan.update(method=method, physical_repeat=repeat, stage1_result_receipt=result_receipt,
        stage1_public_receipt_origin="original_stage1_result" if result.get("public_input") else
        "supplemental_receipt_of_existing_stage1_public_input; original_result_lacked_receipt; stage1_unchanged")
    plan["plan_sha256"] = _digest(plan)
    return plan


def write_preparation(plan, path):
    """Write a new immutable preparation file; never replace an earlier plan."""
    _verify_plan(plan)
    path = paired._output(path); paired._write(path, plan)
    return _receipt(path)


def _verify_plan(plan):
    checked = copy.deepcopy(plan); digest = checked.pop("plan_sha256", None)
    if digest != _digest(checked) or plan.get("repeats") != 3 or plan.get("max_target_executions") != 12 or set(plan["arms"]) != set(ARMS):
        raise ValueError("frozen_target_plan_changed")
    receipts = plan["implementation"] + plan["material_authorities"] + [plan["planning_receipt"]]
    if plan.get("stage1_result_receipt"):
        receipts.append(plan["stage1_result_receipt"])
    if plan.get("runner_policy_receipt"):
        receipts += [plan["runner_policy_receipt"], plan["runner_policy"]["qualification_receipt"]]
    for bound in receipts:
        _read(bound, json_value=False)


_BINARY_RECEIPT = r'''
import hashlib,json,os,pathlib,stat,sys
request=json.load(sys.stdin);p=pathlib.PurePosixPath(request['path'])
if str(p)!=request['path'] or not p.is_absolute() or '..' in p.parts or p.parts[1] not in ('app','tmp'):raise ValueError('binary_path')
for parent in list(reversed(p.parents)) + [p]:
    if os.path.islink(str(parent)):raise ValueError('binary_symlink')
s=os.stat(str(p))
if not stat.S_ISREG(s.st_mode) or not s.st_mode & 0o111:raise ValueError('binary_not_regular_executable')
h=hashlib.sha256()
with open(str(p),'rb') as f:
    for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
after=os.stat(str(p))
if (s.st_size,s.st_mtime_ns,s.st_ino)!=(after.st_size,after.st_mtime_ns,after.st_ino):raise ValueError('binary_changed_during_hash')
print(json.dumps({'status':'complete','path':str(p),'sha256':h.hexdigest(),'bytes':s.st_size,'mode':stat.S_IMODE(s.st_mode),'mtime_ns':s.st_mtime_ns}))
'''


def _execute_arm(plan, arm, directory):
    """Runtime entry only: one fresh clone, writes, build receipts, then test."""
    if not arm["build_steps"]:
        return runtime.execute_variant(plan["checkpoint"], directory, arm["command"], plan["test_timeout_seconds"],
            files=arm["files"], observation_paths=plan["observation_paths"], env=plan["environment"],
            workdir=arm["working_directory"], resources=plan["resources"])
    directory.mkdir(parents=True, exist_ok=False)
    result = {"status": "prepared", "checkpoint": plan["checkpoint"], "execution": None, "builds": [], "observations": []}
    paired._write(directory / "plan.json", {"arm": arm, "checkpoint": plan["checkpoint"], "timeout": plan["test_timeout_seconds"]})
    try:
        with runtime.Container(plan["checkpoint"]["image_id"], directory / "container", plan["checkpoint"]["head"], **plan["resources"]) as container:
            writes = runtime._control_json(container, runtime._FILES,
                {"operation": "write", "files": runtime._file_specs(arm["files"])}, directory / "writes")
            result["file_receipts"] = writes
            if writes.get("status") != "complete":
                result["status"] = "file_precondition_failed"
            else:
                for index, step in enumerate(arm["build_steps"]):
                    built = runtime._run(container, step["command"], plan["test_timeout_seconds"],
                        directory / f"build_{index:02d}", plan["environment"], step["working_directory"])
                    result["builds"].append(built)
                    if built.get("status") != "completed" or built.get("returncode") != 0:
                        result["status"] = "build_failed"; break
                    binary = runtime._control_json(container, _BINARY_RECEIPT, {"path": step["expected_binary_path"]}, directory / f"binary_{index:02d}")
                    built["fresh_binary_receipt"] = binary
                    if (binary.get("status") != "complete" or binary.get("path") != step["expected_binary_path"]
                            or not isinstance(binary.get("sha256"), str) or not re.fullmatch(r"[0-9a-f]{64}", binary["sha256"])
                            or type(binary.get("bytes")) is not int or binary["bytes"] < 0
                            or type(binary.get("mode")) is not int or not binary["mode"] & 0o111):
                        result["status"] = "build_binary_receipt_failed"; break
                    if re.search(r"\bcargo\s+test\b", step["command"]) and "--no-run" in step["command"]:
                        relative = step["expected_binary_path"].removeprefix("/app/")
                        output = built.get("stdout", "") + "\n" + built.get("stderr", "")
                        if relative not in output:
                            result["status"] = "build_receipt_did_not_name_exact_executable"; break
                else:
                    execution = runtime._run(container, arm["command"], plan["test_timeout_seconds"],
                        directory / "test", plan["environment"], arm["working_directory"])
                    result.update(execution=execution, status=execution["status"])
                    if plan["observation_paths"] and not execution.get("transport_error"):
                        captured = runtime._read_files(container, plan["observation_paths"], directory / "observations")
                        result["observations"] = captured.get("files", [])
    except Exception as error:
        result.update(status="runtime_error", error_type=type(error).__name__, error=str(error))
    paired._write(directory / "result.json", result)
    return result


def execute_preparation(preparation_receipt, out):
    """At most 12 target runs. Existing complete or partial output is never rerun."""
    plan = _read(preparation_receipt); _verify_plan(plan)
    out = paired._output(out)
    if out.exists():
        raise FileExistsError("target_output_exists; completed_or_partial_attempt_preserved_no_redispatch")
    out.mkdir(parents=True)
    paired._write(out / "execution_binding.json", {"preparation": preparation_receipt, "plan_sha256": plan["plan_sha256"]})
    records = []; diagnoses = {}; comparisons = []
    for repeat in range(1, 4):
        for name in ARMS:
            arm = plan["arms"][name]
            if arm["status"] != "prepared":
                records.append({"repeat": repeat, "arm": name, "status": "staging_failure", "reason": arm["reason"]}); continue
            directory = out / f"repeat_{repeat:02d}" / name
            result = _execute_arm(plan, arm, directory)
            diagnosis = paired._diagnose(result, directory)
            paired._write(directory / "diagnosis.json", diagnosis)
            diagnoses[(repeat, name)] = diagnosis
            records.append({"repeat": repeat, "arm": name, "status": result.get("status"),
                            "result": _receipt(directory / "result.json"), "diagnosis": _receipt(directory / "diagnosis.json")})
        left, right = (diagnoses.get((repeat, name)) for name in ("p_instrumented", "q_instrumented"))
        if left is not None and right is not None:
            comparisons.append({"repeat": repeat, **paired._comparison(left, right)})
    instrumented = [diagnoses.get((r, a)) for r in range(1, 4) for a in ("p_instrumented", "q_instrumented")]
    channels = all(d and d["effects"] and d["observations"] and not d["event_errors"]
                   and d["execution_status"] == "completed" and d["timed_out"] is not True for d in instrumented)
    alignment = len(comparisons) == 3 and all(c.get("comparison") and all(
        c["comparison"]["channels"][channel]["status"] == "aligned" for channel in ("effect", "observation")) for c in comparisons)
    # These are prerequisites, never a semantic identity or noninterference vote.
    pending = {"qualified_for_stage2": False, "status": "pending_independent_technical_audit",
        "actual_both_channels_every_instrumented_repeat": bool(channels),
        "structural_event_alignment_complete": bool(alignment),
        "semantic_identity_qualified": None, "noninterference_qualified": None,
        "missing_observations_never_filled_from_declared_anchors": True,
        "method_output_preserved_without_repairs": True, "planning": plan["planning_receipt"]}
    if not channels or not alignment:
        pending["status"] = "measurement_unusable_pending_audit"
    if channels and alignment:
        feedback = {"before_effects": [], "original_observations": [],
                    "scope": "Observed instrumented P/Q events only; unusable for stage2 until independent qualification."}
        for repeat in range(1, 4):
            feedback["before_effects"].append({"repeat": repeat, **{
                p: diagnoses[(repeat, p + "_instrumented")]["effects"] for p in ("p", "q")}})
            feedback["original_observations"].append({"repeat": repeat, **{
                p: diagnoses[(repeat, p + "_instrumented")]["observations"] for p in ("p", "q")}})
        paired._write(out / "public_feedback_candidate.json", feedback)
        pending["public_feedback_candidate"] = _receipt(out / "public_feedback_candidate.json")
    paired._write(out / "qualification_pending.json", pending)
    summary = {"version": "track-b-target-execution.v1", "case_id": plan["case_id"],
        "preparation": preparation_receipt, "planning": plan["planning_receipt"], "runs": records,
        "subject_command_executions": len(diagnoses), "max_target_executions": 12,
        "comparisons": comparisons, "qualification_pending": _receipt(out / "qualification_pending.json"),
        "qualified_for_stage2": False, "scientific_label": None, "semantic_repair_performed": False,
        "status": "executed_pending_independent_technical_audit"}
    paired._write(out / "summary.json", summary)
    paired._write(out / "completion.json", {"summary": _receipt(out / "summary.json")})
    return summary
