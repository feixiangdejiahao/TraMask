"""Frozen trial selection and source preparation for the 30-trial pilot.

The generation registry contains public inputs only. Manual annotations stay
in a separate evaluation file and never enter augmentation.prepare().
"""
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tomllib

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT)]
RUN = ROOT / "experiments/relation_distinction/results/pilot30_20261007_v1"
SEED = "20261007-pilot30-v1:"


def read(path):
    return json.loads(Path(path).read_text())


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def receipt(path):
    return {"path": str(path.resolve()), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def select():
    if (RUN / "protocol.json").exists():
        return read(RUN / "cases.json")
    census_path = ROOT / "research/combination_relation_census_20261007/census.json"
    eligible = []
    for row in read(census_path)["records"]:
        source = ROOT / "results/deepswe_failure_manual_20261006/trials" / row["trial"]
        task = tomllib.loads((source / "task.toml").read_text())
        language = task["metadata"]["language"]
        if row["category"] == "no_confirmed" or language not in {"python", "go", "typescript"}:
            continue
        eligible.append((row, task, source))
    chosen = []
    for language in ("python", "go", "typescript"):
        used = set()
        for multi, count in ((True, 4), (False, 6)):
            pool = [x for x in eligible if x[1]["metadata"]["language"] == language
                    and (("M" in x[0]["classes"]) == multi)]
            pool.sort(key=lambda x: hashlib.sha256((SEED + x[0]["trial"]).encode()).hexdigest())
            taken = []
            for item in pool:
                if item[0]["task"] in used:
                    continue
                used.add(item[0]["task"])
                taken.append(item)
                if len(taken) == count:
                    break
            if len(taken) != count:
                raise ValueError("insufficient_selection_stratum")
            chosen.extend(taken)
    cases, truth = [], []
    for index, (row, task, source) in enumerate(chosen, 1):
        case_id = f"T{index:02}"
        case = {"id": case_id, "trial": row["trial"], "task": row["task"],
                "language": task["metadata"]["language"], "base_commit": task["metadata"]["base_commit_hash"],
                "image": task["environment"]["docker_image"],
                "repository": str(RUN / "cases" / case_id / "repository"),
                "candidate_patch": str(source / "model.patch"), "issue": str(source / "instruction.md"),
                "trajectory": str(source / "trajectory.json"),
                "input_receipts": [receipt(source / p) for p in ("model.patch", "instruction.md", "trajectory.json")]}
        cases.append(case)
        truth.append({"id": case_id, **row})
    protocol = {"created_at": datetime.now(timezone.utc).isoformat(), "model": "deepseek-v4-flash",
                "sample_size": 30, "eligible_trials": len(eligible), "seed": SEED,
                "selection": "SHA256 ordering; 10 per language; 4 with multi-relation gaps and 6 single-only; one trial per task; no replacement after outcome inspection.",
                "census": receipt(census_path), "model_input_exclusions": ["manual gap annotations", "reference solutions", "hidden verifier tests", "benchmark outcome labels"],
                "algorithm": [receipt(p) for p in sorted((ROOT / "src/augmentation").glob("*.py"))],
                "detection_trial_success": "At least one independently confirmed combination-gap claim in the trial.",
                "known_gap_recall": "Count distinct original confirmed gap entries matched by model claims. Unmatched known entries are omissions; report unknown and technical failures separately.",
                "false_positive": "A distinct model gap claim refuted by public requirement, original validation or source. Merely absent from old labels is not sufficient.",
                "correct_test": "A collected executable test combines the required conditions, makes a contract-supported discriminating assertion, and retains necessary shared object/state. Passing and valid assertion failure both qualify.",
                "positive_only_limit": "No task-level false-positive rate or specificity can be estimated from these 30 positive trials.",
                "execution": "Fresh original benchmark image plus submitted patch. Generated tests are frozen before execution. No adaptive expected-value repair.",
                "model_calls_started": False}
    write(RUN / "cases.json", cases)
    write(RUN / "evaluation_truth.json", truth)
    write(RUN / "protocol.json", protocol)
    return cases


def materialize(case):
    from scripts.prepare_relational_gap_cases import materialize as restore
    directory = RUN / "cases" / case["id"]
    directory.mkdir(parents=True, exist_ok=True)
    try:
        available = subprocess.run(["docker", "image", "inspect", case["image"]], capture_output=True)
        if available.returncode:
            with (directory / "image_pull.log").open("wb") as log:
                subprocess.run(["docker", "pull", case["image"]], stdout=log, stderr=subprocess.STDOUT,
                               check=True, timeout=3600)
        resolved = dict(case)
        if len(case["base_commit"]) < 40:
            full = subprocess.check_output(["docker", "run", "--rm", "--network", "none", "--entrypoint", "git",
                case["image"], "-c", "safe.directory=/app", "-C", "/app", "rev-parse", case["base_commit"] + "^{commit}"], text=True).strip()
            if not full.startswith(case["base_commit"]):
                raise ValueError("abbreviated_base_commit_does_not_match")
            resolved.update(declared_base_commit=case["base_commit"], base_commit=full)
        result = restore(resolved, False)
    except Exception as exc:
        result = {**case, "repository_status": "preparation_error", "error_type": type(exc).__name__, "error": str(exc)}
    write(directory / "materialization.json", result)
    return result


def extract(case):
    directory = RUN / "cases" / case["id"]
    prepared = directory / "prepared.json"
    if prepared.exists():
        return {"id": case["id"], "status": "complete", "counts": read(prepared)["counts"]}
    if not (directory / "repository_provenance.json").exists():
        return {"id": case["id"], "status": "missing_repository"}
    command = [sys.executable, "-m", "augmentation", "prepare", "--repository", case["repository"],
               "--patch", case["candidate_patch"], "--issue", case["issue"], "--trajectory", case["trajectory"],
               "--output", str(prepared)]
    import os
    try:
        with (directory / "extract.stdout").open("wb") as out, (directory / "extract.stderr").open("wb") as err:
            done = subprocess.run(command, cwd=ROOT, env={**os.environ, "PYTHONPATH": str(ROOT / "src"),
                                  "PYTHONDONTWRITEBYTECODE": "1"}, stdout=out, stderr=err, timeout=1800)
        result = {"id": case["id"], "status": "complete" if done.returncode == 0 else "analysis_error",
                  "returncode": done.returncode, "command": command}
        if done.returncode == 0:
            result["counts"] = read(prepared)["counts"]
    except subprocess.TimeoutExpired:
        result = {"id": case["id"], "status": "analysis_timeout", "timeout_seconds": 1800}
    write(directory / "extraction.json", result)
    return result


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument("action", choices=("select", "materialize", "extract"))
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--case", action="append")
    args = parser.parse_args()
    cases = select()
    if args.action == "select":
        print(json.dumps({"cases": len(cases), "protocol": str(RUN / "protocol.json")}))
        return
    selected = [c for c in cases if args.case is None or c["id"] in args.case]
    function = materialize if args.action == "materialize" else extract
    results = []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        for future in as_completed([pool.submit(function, case) for case in selected]):
            result = future.result()
            results.append(result)
            print(json.dumps({k: result[k] for k in ("id", "status", "repository_status", "error_type", "counts") if k in result}), flush=True)
            write(RUN / (args.action + "_summary.json"), results)


if __name__ == "__main__":
    main()
