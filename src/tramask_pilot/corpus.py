"""Label-blind source packets and reproducible task-level sampling."""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import tomllib

ROOT = Path(__file__).resolve().parents[2]
RUN = ROOT / "results/behavioral_masking/20261023_tramask_replay_n40_r01"
FAILURES = ROOT / "results/failure_analysis/deepswe_failed_trials_n211_20261006/trials"
INDEX = ROOT / "results/benchmark_datasets/expanded_trial_dataset_20260926/index/trials.json"
TASKS = Path("/home/jhx/oracle_gap/external/deep-swe/tasks")
SEED = "tramask-20261023-v1"
CALIBRATION_TASKS = ("kombu-virtual-queue-dead-lettering", "koota-query-predicates", "abs-stepped-slices")


def read(path):
    return json.loads(Path(path).read_text())


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def receipt(path):
    path = Path(path)
    return {"path": str(path.resolve()), "bytes": path.stat().st_size,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def order(value):
    return hashlib.sha256((SEED + ":" + value).encode()).hexdigest()


def case(row, case_id):
    source = FAILURES / row["trial_name"]
    task_path = source / "task.toml" if source.exists() else TASKS / row["task_name"] / "task.toml"
    cfg = tomllib.loads(task_path.read_text())
    return {"id": case_id, "trial": row["trial_name"], "task": row["task_name"],
            "language": cfg["metadata"]["language"], "model": row["model"],
            "cohort": "failed" if row["outcome"] == "fail" else "successful",
            "base_commit": cfg["metadata"]["base_commit_hash"],
            "image": cfg["environment"]["docker_image"], "source": str(source) if source.exists() else None,
            "task_directory": str(TASKS / row["task_name"])}


def initialize():
    if (RUN / "selection_order.json").exists():
        return read(RUN / "selection_order.json")
    fail_rows = [read(p) for p in sorted(FAILURES.glob("*/metadata.json"))]
    assert len(fail_rows) == len({r["trial_name"] for r in fail_rows}) == 211
    missing = [{"trial": r["trial_name"], "file": name} for r in fail_rows
               for name in ("instruction.md", "task.toml", "model.patch", "trajectory.json")
               if not (FAILURES / r["trial_name"] / name).is_file()]
    audit = {"created_at": datetime.now(timezone.utc).isoformat(), "trials": len(fail_rows),
             "tasks": len({r["task_name"] for r in fail_rows}),
             "models": dict(Counter(r["model"] for r in fail_rows)), "missing_files": missing,
             "source_index": receipt(INDEX), "paper": receipt(ROOT / "TraMask_Behavioral_Masking.pdf"),
             "artifacts": {r["trial_name"]: [receipt(FAILURES / r["trial_name"] / n)
                           for n in ("instruction.md", "task.toml", "model.patch", "trajectory.json")]
                           for r in fail_rows}}
    write(RUN / "corpus_audit.json", audit)
    calibration = []
    for i, task in enumerate(CALIBRATION_TASKS, 1):
        chosen = min((r for r in fail_rows if r["task_name"] == task), key=lambda r: order(r["trial_name"]))
        calibration.append(case(chosen, f"C{i:02}"))
    def unique_tasks(rows, prefix):
        chosen = []
        tasks = sorted({r["task_name"] for r in rows} - set(CALIBRATION_TASKS), key=order)
        for i, task in enumerate(tasks, 1):
            row = min((r for r in rows if r["task_name"] == task), key=lambda r: order(r["trial_name"]))
            chosen.append(case(row, f"{prefix}{i:03}"))
        return chosen
    successes = [r for r in read(INDEX)["rows"] if r.get("source") == "deep-swe"
                 and r.get("model") == "deepseek-v4-flash" and r.get("outcome") == "pass"
                 and r.get("has_trajectory") and r.get("has_model_patch")]
    result = {"seed": SEED, "calibration": calibration, "failed_order": unique_tasks(fail_rows, "F"),
              "successful_order": unique_tasks(successes, "S"), "successful_index_trials": len(successes),
              "selection_rule": "Task SHA256 order, then one trial per task by SHA256; calibration tasks excluded. Complete replay eligibility in this order before masking assessment. Stop at 30 eligible failures and 10 eligible successes. Keep all exclusions. Successful tasks already selected among failures are skipped to prefer distinct tasks.",
              "not_used_for_selection": ["previous gap labels", "verifier output", "repair outcomes", "masking hypotheses"]}
    write(RUN / "selection_order.json", result)
    return result


def calls(document):
    """Keep exact command and its corresponding archived result; no private reasoning."""
    rows = []
    for ordinal, step in enumerate(document.get("steps", [])):
        tool_calls = step.get("tool_calls") or []
        observations = (step.get("observation") or {}).get("results") or []
        for index, call in enumerate(tool_calls):
            args = call.get("arguments", {})
            if isinstance(args, str):
                args = json.loads(args)
            if not isinstance(args, dict) or not isinstance(args.get("command"), str):
                continue
            expected = None
            if len(observations) == len(tool_calls):
                content = observations[index].get("content")
                try:
                    expected = json.loads(content) if isinstance(content, str) else content
                except ValueError:
                    expected = {"output": content}
            rows.append({"id": f"s{step.get('step_id', ordinal)}_c{index}",
                         "step_id": step.get("step_id", ordinal), "ordinal": ordinal, "call_index": index,
                         "function": call.get("function_name"), "command": args["command"],
                         "expected": expected, "observation_mapping_unambiguous": expected is not None,
                         "agent_message": step.get("message", "")})
    return rows


def input_directory(c):
    return RUN / "inputs" / c["id"]


def public_packet(c):
    d = input_directory(c)
    actions = calls(read(d / "trajectory.json"))
    return {"case_id": c["id"], "language": c["language"],
            "issue": (d / "instruction.md").read_text(), "final_patch": (d / "model.patch").read_text(),
            "actions": [{"id": a["id"], "command": a["command"],
                         "output": str((a["expected"] or {}).get("output", ""))[:1200],
                         "returncode": (a["expected"] or {}).get("returncode")} for a in actions]}
