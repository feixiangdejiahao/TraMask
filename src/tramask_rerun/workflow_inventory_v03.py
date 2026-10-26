"""New evidence execution phases with explicit run-local artifacts."""
from __future__ import annotations
import json
from pathlib import Path

from tramask_pilot.corpus import calls, read, receipt
from tramask_pilot.fidelity import test_evidence
from tramask_pilot.submission_replay import ENV
from .runtime import execute_variant
from .study import RUN, now, sha, write_new


def baseline(case, run=RUN, *, capsule=False):
    run = Path(run)
    protocol = run / ("capsule_baseline_protocol.json" if capsule else "baseline_protocol.json")
    if not protocol.exists():
        raise ValueError("Baseline execution requires frozen protocol")
    selected = read(run / "runs" / case["id"] / "selection.json")
    out = run / "runs" / case["id"] / ("baseline_capsule" if capsule else "baseline")
    if (out / "summary.json").exists():
        return read(out / "summary.json")
    export = read(out.parent / "terminal_sources/result.json")
    present = {row["path"] for row in export.get("files", []) if row.get("status") == "present"}
    missing_tests = [path for path in selected["test_paths"] if path not in present]
    file_specs = {}
    capsule_receipt = None
    if capsule:
        capsule_path = out.parent / "historical_test_capsule.json"
        recovered = read(capsule_path)
        if recovered.get("approved_for_explicit_harness_materialization") is not True:
            raise ValueError("Unqualified historical test capsule")
        for path, row in recovered["files"].items():
            if path in present or sha(row["content"]) != row["sha256"]:
                raise ValueError("Capsule must not overwrite extant terminal files")
            file_specs[path] = {"content": row["content"], "new_file": True}
        capsule_receipt = receipt(capsule_path)
    records = []
    for repeat in (1, 2, 3):
        directory = out / f"repeat_{repeat:02d}"
        result_path = directory / "result.json"
        if result_path.exists():
            result = read(result_path)
        elif directory.exists():
            raise RuntimeError("Incomplete baseline attempt retained; inspect before any new attempt: " + str(directory))
        else:
            result = execute_variant(case["checkpoint"], directory, selected["command"],
                case["test_timeout_seconds"], files=file_specs, observation_paths=selected["observation_paths"],
                env=ENV, workdir=selected["working_directory"], resources=case["resources"])
        execution = result.get("execution") or {}
        text = execution.get("stdout", "") + "\n" + execution.get("stderr", "")
        facts = test_evidence(text)
        records.append({"repeat": repeat, "result": receipt(result_path),
                        "status": result.get("status"), "returncode": execution.get("returncode"),
                        "timed_out": execution.get("timed_out"), "runner_text_facts": facts,
                        "elapsed_seconds": execution.get("elapsed_seconds")})
    summary = {"case_id": case["id"], "created_at": now(), "checkpoint": case["checkpoint"],
               "baseline_protocol": receipt(protocol), "selection": receipt(out.parent / "selection.json"),
               "runs": records, "subject_test_executions": len(records),
               "missing_selected_test_paths": missing_tests,
               "historical_test_capsule": capsule_receipt,
               "status": "executed_pending_evidence_qualification",
               "scope": ("Explicit original test capsule on terminal P. " if capsule else "Native terminal context. ") + "Unmodified selected command. No inference of test PASS from shell status; absent tests/no collection require separate qualification. Whole stdout equality is not an acceptance criterion."}
    write_new(out / "summary.json", summary)
    return summary


def public_packet(case, run=RUN):
    """Construct only raw authorized inputs; never read reviews or old hypotheses."""
    run = Path(run)
    input_dir = run / "inputs" / case["id"]
    selected = read(run / "runs" / case["id"] / "selection.json")
    exported = read(run / "runs" / case["id"] / "terminal_sources/result.json")
    files = {row["path"].lstrip("/"): row["content"] for row in exported.get("files", [])
             if row.get("status") == "present" and isinstance(row.get("content"), str)}
    capsule_path = run / "runs" / case["id"] / "historical_test_capsule.json"
    if capsule_path.exists():
        capsule = read(capsule_path)
        if capsule.get("approved_for_explicit_harness_materialization") is not True:
            raise ValueError("Unqualified test capsule")
        for path, row in capsule["files"].items():
            if path.lstrip("/") in files or sha(row["content"]) != row["sha256"]:
                raise ValueError("Capsule source receipt changed or overwrites terminal file")
            files[path.lstrip("/")] = row["content"]
    test_names = {path.lstrip("/") for path in selected["test_paths"]}
    tests = {name: content for name, content in files.items() if name in test_names}
    sources = {name: content for name, content in files.items() if name not in test_names}
    test = {"id": "original_validation", "command": selected["command"], "files": tests,
            "working_directory": selected["working_directory"],
            "target": selected["target"], "target_anchor": selected["target_anchor"],
            "execution_call_id": selected["execution_call_id"]}
    packet = {"id": case["id"], "case_id": case["id"],
              "issue": (input_dir / "instruction.md").read_text(),
              "final_patch": (input_dir / "model.patch").read_text(),
              "selected_test": test, "validation_tests": [test], "final_sources": sources,
              "actions": [{"id": action["id"], "command": action["command"],
                           "output": (action["expected"] or {}).get("output", ""),
                           "returncode": (action["expected"] or {}).get("returncode")}
                          for action in calls(read(input_dir / "trajectory.json"))]}
    return packet


def end_to_end_packet(case, run=RUN):
    """Track B uses a complete, version-bound inventory independent of P1.

Historical test bytes are explicit input strata after terminal-state proof;
they never replace terminal production source. The chosen version must later
be materialized with its exact terminal predecessor hash by the evaluator.
"""
    run = Path(run)
    directory = run / "runs" / case["id"]
    qualification_path = directory / "qualified_validation_inventory.json"
    if not qualification_path.exists():
        raise ValueError("Track B requires independent all-validation-test inventory qualification; P1 singleton fallback is forbidden")
    qualification = read(qualification_path)
    if qualification.get("inventory_complete_for_declared_recovery_scope") is not True:
        raise ValueError("Unqualified Track B validation inventory")
    exported = read(directory / "terminal_sources/result.json")
    contents = {row["path"].lstrip("/"): row["content"] for row in exported.get("files", [])
                if row.get("status") == "present" and isinstance(row.get("content"), str)}
    for bound in qualification.get("source_exports", []):
        if receipt(bound["path"]) != bound:
            raise ValueError("Supplemental public source receipt changed")
        supplement = read(bound["path"])
        for row in supplement.get("files", []):
            if row.get("status") != "present" or not isinstance(row.get("content"), str):
                continue
            path = row["path"].lstrip("/")
            if path in contents and contents[path] != row["content"]:
                raise ValueError("Conflicting terminal source exports")
            contents[path] = row["content"]
    validation_tests = []
    for test in qualification["validation_tests"]:
        if "files" in test:
            files = dict(test["files"])
            if set(files) != {path.lstrip("/") for path in test["test_paths"]}:
                raise ValueError("Versioned test paths and contents disagree")
            bindings = test.get("file_receipts", {})
            for path, content in files.items():
                from .variants import _path
                if _path(path) != path or not isinstance(content, str):
                    raise ValueError("Noncanonical versioned test content")
                bound = bindings.get(path, {})
                if sha(content) != bound.get("sha256"):
                    raise ValueError("Versioned test content hash mismatch")
                authority = bound.get("authority_receipt")
                if not isinstance(authority, dict) or receipt(authority["path"]) != authority:
                    raise ValueError("Versioned test authority receipt mismatch")
            if test.get("materialization", {}).get("production_overlay") is True:
                raise ValueError("Historical test inventory cannot overlay production source")
        else:
            files = {path.lstrip("/"): contents[path.lstrip("/")] for path in test["test_paths"]}
        entry = {"id": test["id"], "command": test["command"],
                 "working_directory": test["working_directory"],
                 "files": files}
        if test.get("inline_test"):
            inline = test["inline_test"]
            if "path" in inline:
                entry["inline_test"] = inline
            else:
                content = inline["content"]
                if sha(content) != inline["sha256"] or test["command"].count(content) != 1:
                    raise ValueError("Inline test requires one exact raw command range")
                start = test["command"].index(content)
                start_byte = len(test["command"][:start].encode())
                suffix = {"python": "py", "javascript": "js", "typescript": "ts", "bash": "sh"}.get(inline.get("language"), "txt")
                virtual = "tmp/tramask_inline/" + sha(content) + "." + suffix
                entry["files"][virtual] = content
                entry["inline_test"] = {"path": virtual, "text": content, "command_mapping": {
                    "original_command": test["command"], "script_start_byte": start_byte,
                    "script_end_byte": start_byte + len(content.encode())}}
        validation_tests.append(entry)
    if not validation_tests:
        raise ValueError("No qualified original validation tests")
    inputs = run / "inputs" / case["id"]
    packet = {"id": case["id"], "case_id": case["id"],
              "issue": (inputs / "instruction.md").read_text(),
              "final_patch": (inputs / "model.patch").read_text(), "validation_tests": validation_tests,
              "actions": [{"id": action["id"], "command": action["command"],
                           "output": (action["expected"] or {}).get("output", ""),
                           "returncode": (action["expected"] or {}).get("returncode")}
                          for action in calls(read(inputs / "trajectory.json"))]}
    test_paths = {path for test in validation_tests for path in test["files"]}
    shared = {path.lstrip("/") for path in qualification.get("production_test_shared_paths", [])}
    packet["final_sources"] = {path: content for path, content in contents.items() if path not in test_paths or path in shared}
    return packet
