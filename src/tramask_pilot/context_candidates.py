"""Stage and execute manually approved fixed-Q test candidates in fresh clones."""
from pathlib import Path
import shutil
import subprocess

from .corpus import RUN, read, receipt, write
from .hypotheses import apply_exact_edits, parse_events


def merge_measurement(candidate_text, original_text, measured_text, scratch):
    """Three-way textual merge; conflicts fail closed, never resolved by guessing."""
    scratch = Path(scratch)
    scratch.mkdir(parents=True, exist_ok=True)
    paths = []
    for name, content in (("candidate", candidate_text), ("base", original_text), ("measured", measured_text)):
        path = scratch / name
        path.write_text(content)
        paths.append(path)
    result = subprocess.run(["git", "merge-file", "-p", *map(str, paths)], capture_output=True)
    (scratch / "stdout.bin").write_bytes(result.stdout)
    (scratch / "stderr.bin").write_bytes(result.stderr)
    write(scratch / "receipt.json", {"inputs": [receipt(path) for path in paths],
                                     "returncode": result.returncode})
    if result.returncode:
        raise ValueError("candidate_measurement_merge_conflict")
    return result.stdout.decode()


def stage(case_id, candidate_dir):
    candidate_dir = Path(candidate_dir)
    candidate = read(candidate_dir / "candidate.json")
    review = read(candidate_dir / "manual_review.json")
    if review.get("approved_for_execution") is not True or review.get("candidate_sha256") != receipt(candidate_dir / "candidate.json")["sha256"]:
        raise ValueError("candidate_lacks_matching_manual_approval")
    case = RUN / "runs" / case_id
    hdir = Path(read(case / "active_hypothesis.json")["directory"])
    base_staging = read(hdir / "staging.json")
    staging_path = candidate_dir / "staging.json"
    if staging_path.exists():
        return read(staging_path)
    edits = candidate["edits"]
    changed_paths = sorted({edit["path"] for edit in edits})
    result = {"case_id": case_id, "candidate": receipt(candidate_dir / "candidate.json"),
              "fixed_hypothesis": receipt(hdir / "hypothesis.json"), "variants": {}}
    for name in ("p_original", "q_original", "p_instrumented", "q_instrumented"):
        base = Path(base_staging["variants"][name]["tree"])
        dest = candidate_dir / "variants" / name
        if dest.exists():
            raise FileExistsError(dest)
        shutil.copytree(base, dest)
        if name.endswith("_original"):
            apply_exact_edits(dest, edits)
            for new_file in candidate.get("new_files", []):
                p = dest / new_file["path"]
                p.parent.mkdir(parents=True, exist_ok=True)
                if p.exists():
                    raise ValueError("new_test_overwrites_file")
                p.write_text(new_file["content"])
        else:
            original_name = name.replace("instrumented", "original")
            original = Path(base_staging["variants"][original_name]["tree"])
            edited = candidate_dir / "variants" / original_name
            conflict = None
            for index, path in enumerate(changed_paths):
                try:
                    combined = merge_measurement((edited / path).read_text(), (original / path).read_text(),
                                                 (base / path).read_text(), candidate_dir / "merge_receipts" / name / str(index))
                except ValueError as error:
                    conflict = {"variant": name, "path": path, "reason": str(error)}
                    break
                (dest / path).write_text(combined)
            if conflict:
                result.setdefault("instrumentation_unavailable", []).append(conflict)
                continue
            for new_file in candidate.get("new_files", []):
                p = dest / new_file["path"]
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(new_file["content"])
        result["variants"][name] = {"tree": str(dest), "command": base_staging["variants"][name]["command"],
                                     "files": [receipt(p) for p in sorted(dest.rglob("*")) if p.is_file()]}
    write(staging_path, result)
    return result


def execute(case_id, candidate_dir):
    from .runtime import Container
    from .experiment import activate_generated_runtime, collect_observation_files
    candidate_dir = Path(candidate_dir)
    out = candidate_dir / "paired_execution"
    if (out / "summary.json").exists():
        return read(out / "summary.json")
    variants = stage(case_id, candidate_dir)
    case = RUN / "runs" / case_id
    replay = Path(read(case / "active_replay.json")["directory"])
    checkpoint = read(replay / "summary.json")["final_context_checkpoint"]
    snapshot = read(replay / "test_snapshot.json")
    records = {}
    for name, variant in variants["variants"].items():
        directory = out / name
        if (directory / "execution.json").exists():
            records[name] = read(directory / "execution.json")
            continue
        with Container(checkpoint["image_id"], directory / "container", checkpoint["head"]) as runtime:
            tree = Path(variant["tree"])
            for path in sorted(tree.rglob("*")):
                if path.is_file():
                    runtime.copy_to(path, "/" + path.relative_to(tree).as_posix())
            activation = activate_generated_runtime(runtime, case)
            execution = runtime.exec(variant["command"], "test", timeout=180,
                                     workdir=snapshot.get("working_directory", "/app"))
            execution["generated_runtime_activation"] = activation
            collect_observation_files(runtime, snapshot.get("observation_paths", []), directory / "observation_files", execution)
            try:
                execution["events"] = parse_events(execution["stdout"] + "\n" + execution["stderr"] + "\n" +
                    "\n".join(row.get("content", "") for row in execution["observation_files"]))
            except ValueError as error:
                execution.update(events=[], event_error=str(error))
            write(directory / "execution.json", execution)
            records[name] = execution
    summary = {"case_id": case_id, "candidate": receipt(candidate_dir / "candidate.json"),
               "status": "executed_pending_contract_and_observation_review", "executions": {
                   name: {key: row.get(key) for key in ("returncode", "timed_out", "transport_error", "event_error", "elapsed_seconds")}
                   for name, row in records.items()},
               "not_a_label": "Shell exit agreement is not observation equality or contract validity; inspect original tests and raw traces."}
    write(out / "summary.json", summary)
    return summary
