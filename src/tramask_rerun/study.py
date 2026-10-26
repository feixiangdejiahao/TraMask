"""Explicit new-run inputs and terminal-state provenance; never old labels."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
import tomllib

from tramask_pilot.corpus import ROOT, RUN as OLD_RUN, calls, read, receipt
from tramask_pilot.submission_replay import state_directory

RUN = ROOT / "results/behavioral_masking/20261023_tramask_evidence_n60_r01"
PREPARATION = ROOT / "experiments/behavioral_masking/20261023_tramask_evidence_preparation01"
INPUT_NAMES = ("instruction.md", "task.toml", "model.patch", "trajectory.json")


def write_new(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode()
    if path.exists():
        if path.read_bytes() != data:
            raise FileExistsError(path)
        return
    with path.open("xb") as stream:
        stream.write(data)


def now():
    return datetime.now(timezone.utc).isoformat()


def sha(data):
    return hashlib.sha256(data if isinstance(data, bytes) else data.encode()).hexdigest()


def original_cases():
    return sum([read(OLD_RUN / f"formal_{k}_cohort.json")["cases"]
                for k in ("failed", "successful")], [])


def validated_checkpoint(case_id):
    directory = state_directory(case_id)
    summary_path = directory / "summary.json"
    validation_path = directory / "validation_v03/report.json"
    summary, validation = read(summary_path), read(validation_path)
    checkpoint = summary["checkpoint"]
    if not (validation["submission_state_status"] == "matched"
            and validation["submitted_commit_tree_matches"]
            and validation["working_tree_matches_submitted_commit"]
            and not validation["subject_files_or_real_index_patched"]
            and validation["image_id"] == checkpoint["image_id"]):
        raise ValueError("Unverified terminal checkpoint: " + case_id)
    patch = OLD_RUN / "inputs" / case_id / "model.patch"
    if receipt(patch)["sha256"] != validation["submitted_patch_sha256"]:
        raise ValueError("Checkpoint patch receipt changed")
    return {"image_id": checkpoint["image_id"], "head": checkpoint["head"],
            "summary": receipt(summary_path), "validation": receipt(validation_path),
            "scope": "Verified submission filesystem, including recorded /tmp and dependencies; not a process-memory snapshot."}


def import_original_inputs(run=RUN):
    """Reuse raw inputs and command identity only, never old verdicts or probes."""
    run = Path(run)
    rows = []
    for case in original_cases():
        src, dst = OLD_RUN / "inputs" / case["id"], run / "inputs" / case["id"]
        dst.mkdir(parents=True, exist_ok=True)
        for name in INPUT_NAMES:
            target = dst / name
            if target.exists():
                if target.read_bytes() != (src / name).read_bytes():
                    raise ValueError("Input differs: " + str(target))
            else:
                shutil.copyfile(src / name, target)
        config = tomllib.loads((dst / "task.toml").read_text())
        checkpoint = validated_checkpoint(case["id"])
        selection_path = OLD_RUN / "runs" / case["id"] / "localization/selection.json"
        command_path = selection_path.with_name("command_review.json")
        selection = read(selection_path)["primary"]
        technical = read(command_path)
        command = technical.get("test_command", selection["test_command"])
        actions = calls(read(dst / "trajectory.json"))
        action = next(a for a in actions if a["id"] == selection["execution_call_id"])
        if not action["command"].strip().endswith(command.strip()):
            raise ValueError("Selected command is no longer an exact archived suffix")
        selected = {"command": command, "working_directory": technical.get("test_workdir", "/app"),
                    "execution_call_id": action["id"], "test_paths": selection["test_paths"],
                    "source_paths": ["/app/" + p for p in selection["source_paths"]],
                    "target": selection["target"], "target_anchor": selection["target_anchor"],
                    "observation_paths": technical.get("observation_paths", []),
                    "selection_receipt": receipt(selection_path), "command_receipt": receipt(command_path),
                    "policy": "Same pre-existing test selection; execute terminal file bytes. No historical source/test overlay."}
        # Configuration and raw issue are public task inputs, not hidden verifier code.
        row = {**case, "partition": "previously_explored", "checkpoint": checkpoint,
               "test_timeout_seconds": float(config["verifier"]["timeout_sec"]),
               "timeout_source": "task.toml:[verifier].timeout_sec",
               "build_timeout_seconds": float(config["environment"]["build_timeout_sec"]),
               "resources": {"cpus": config["environment"].get("cpus", 2),
                             "memory": str(config["environment"].get("memory_mb", 8192)) + "m"},
               "input_receipts": [receipt(dst / n) for n in INPUT_NAMES]}
        write_new(dst / "provenance.json", row)
        write_new(run / "runs" / case["id"] / "selection.json", selected)
        rows.append(row)
    write_new(run / "previously_explored_cases.json", {"cases": rows, "count": len(rows),
        "old_judgments_are_not_new_evidence": True})
    return rows


def patch_paths(patch):
    return list(dict.fromkeys("/app/" + match.group(1) for match in
        re.finditer(r"^\+\+\+ b/(.+)$", patch, flags=re.M)))


def export_paths(case_id, run=RUN):
    """A bounded public allowlist; no recursive evaluator/reference discovery."""
    run = Path(run)
    selected = read(run / "runs" / case_id / "selection.json")
    paths = selected["test_paths"] + selected["source_paths"]
    paths += patch_paths((run / "inputs" / case_id / "model.patch").read_text())
    paths += ["/app/" + name for name in ("package.json", "pyproject.toml", "pytest.ini", "go.mod", "Makefile", "tsconfig.json")]
    return list(dict.fromkeys(paths))
