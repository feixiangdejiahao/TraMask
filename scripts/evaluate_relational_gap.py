"""Independent evaluation of frozen relation candidates and execution records.

No generator, target repository, provider, or runner is imported or executed.
Source-parent identity and runtime outcomes are mechanical; scenario, oracle,
and failure-cause judgments require separate cited review. Unknown is not pass.

inventory --batch-root BATCH [--runs runs.json] --output reviews.json
evaluate --batch-root BATCH --reviews reviews.json --output report.json

runs.json is a list (or {"runs": [...]}) of:
 {"case":"P1", "candidate_id":"...", "role":"generated"|"control",
  "result":"/absolute/result.json", "test_ids":["exact runtime test id"]}
Results may contain normalized tests (id/status), or adjacent junit.xml,
vitest.json, or Go JSON stdout. Aggregate exit codes alone are insufficient.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CENSUS = ROOT / "evaluation_assets/relational_gap_v1/target_census.json"
VERSION = "relational-gap-independent-evaluation-v1"
DIMENSIONS = ("scenario_hit", "correct_oracle", "target_failure_match")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=True,
                                    separators=(",", ":")).encode()).hexdigest()


def read(path: Path):
    return json.loads(path.read_text())


def write_new(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x") as stream:
        json.dump(value, stream, indent=2, ensure_ascii=False)
        stream.write("\n")


def freeze_file(path: Path) -> dict:
    return {"path": str(path.resolve()), "sha256": digest(path)}


def verify_file(record: dict) -> Path:
    path = Path(record["path"])
    if digest(path) != record["sha256"]:
        raise ValueError(f"Frozen evidence changed: {path}")
    return path


def test_parts(identifier: str) -> tuple[str, str]:
    match = re.match(r"^(.*?):\d+:(.*)$", identifier)
    return (match[1], match[2]) if match else ("", identifier)


def parent_hit(identifier: str, target: dict, selection: dict) -> bool:
    path, name = test_parts(identifier)
    aliases = {path}
    source = selection.get("files", {}).get(path, {})
    for key in ("trajectory_source", "original_written_path", "target_path"):
        if source.get(key):
            aliases.add(source[key])
    for anchor in target["source_tests"]:
        if anchor["role"] != "primary":
            continue
        if identifier == anchor["id"]:
            return True
        if name == anchor["name"] and aliases.intersection(anchor["path_aliases"]):
            return True
    return False


def load_batch(root: Path, census: dict) -> tuple[list[dict], list[dict]]:
    entries, frozen = [], []
    known = {row["case"]: row for row in census["cases"]}
    manifests = sorted(root.rglob("prepare.json"))
    if (root / "prepare.json").exists():
        manifests = [root / "prepare.json"]
    for path in manifests:
        if "algorithm_snapshot" in path.parts:
            continue
        manifest = read(path)
        case = manifest.get("case", manifest.get("case_id"))
        if case not in known or manifest.get("status") != "prepared":
            continue
        folder = path.parent
        frozen.append(freeze_file(path))
        for name, expected in manifest["files_sha256"].items():
            file = (folder / name).resolve()
            if not file.is_relative_to(folder.resolve()) or digest(file) != expected:
                raise ValueError(f"Preparation artifact differs: {file}")
            frozen.append(freeze_file(file))
        selection = read(folder / "selection.json")
        candidate_document = read(folder / "candidates.json")
        selected = selection.get("selected_test_ids", [])
        for rank, candidate in enumerate(candidate_document["candidates"], 1):
            parents = list(dict.fromkeys([value for value in
                [candidate.get("base_test_id"), candidate.get("focus_test_id"),
                 *candidate.get("source_test_ids", [])] if value]))
            entries.append({"case": case, "candidate_id": candidate["id"],
                            "batch_directory": str(folder.resolve()), "candidate_rank": rank,
                            "candidate_sha256": canonical(candidate), "source_parent_ids": parents,
                            "target_parent_ids": [p for p in parents if parent_hit(p, known[case], selection)],
                            "selected_target_ids": [p for p in selected if parent_hit(p, known[case], selection)],
                            "test_hit": any(parent_hit(p, known[case], selection) for p in parents)})
    keys = [(r["case"], r["candidate_id"]) for r in entries]
    if len(keys) != len(set(keys)):
        raise ValueError("Repeated case/candidate IDs across batch directories; evaluate one frozen batch at a time")
    return entries, frozen


def load_batches(args, census):
    entries, files = [], []
    for root in [args.batch_root, *getattr(args, "additional_batch_root", [])]:
        current, frozen = load_batch(root, census)
        entries.extend(current)
        files.extend(frozen)
    keys = [(r["case"], r["candidate_id"]) for r in entries]
    if len(keys) != len(set(keys)):
        raise ValueError("Repeated case/candidate across additional batch roots")
    return entries, files


def normal_status(value: str) -> str:
    return {"passed": "pass", "failed": "fail", "skipped": "skip", "pending": "skip",
            "todo": "skip", "disabled": "skip"}.get(value, value)


def runtime_tests(path: Path) -> tuple[list[dict], list[str], list[Path]]:
    document = read(path)
    used, errors = [path], []
    if document.get("error") or document.get("timed_out"):
        errors.append("execution_error_or_timeout")
    if document.get("status") == "error" or document.get("counts", {}).get("error", 0):
        errors.append("reported_run_error")
    if document.get("transport_returncode") not in (None, 0):
        errors.append("transport_error")
    for key in ("process", "transport"):
        item = document.get(key, {})
        if item.get("error") or item.get("timed_out"):
            errors.append(key + "_error")
    tests = document.get("tests")
    if tests is not None:
        rows = [{"id": t.get("id", t.get("name")), "status": normal_status(t.get("status", "unknown")),
                 "kind": t.get("kind"), "message": t.get("message", "")} for t in tests]
    elif (path.parent / "junit.xml").exists():
        file = path.parent / "junit.xml"
        used.append(file)
        rows = []
        for t in ET.parse(file).getroot().iter("testcase"):
            prefix = t.get("classname", "")
            status = "error" if t.find("error") is not None else "fail" if t.find("failure") is not None else "skip" if t.find("skipped") is not None else "pass"
            rows.append({"id": prefix + "::" + t.get("name", ""), "status": status})
    elif (path.parent / "vitest.json").exists():
        file = path.parent / "vitest.json"
        used.append(file)
        rows = [{"id": t.get("fullName", t.get("title", "")), "status": normal_status(t["status"])}
                for suite in read(file).get("testResults", []) for t in suite.get("assertionResults", [])]
    else:
        rows = []
        stdout = path.parent / "stdout.txt"
        if stdout.exists():
            used.append(stdout)
            # Native go test -json records identify leaf tests even after panic.
            for line in stdout.read_text(errors="replace").splitlines():
                try:
                    event = json.loads(line)
                except ValueError:
                    continue
                if event.get("Test") and event.get("Action") in {"pass", "fail", "skip"}:
                    rows.append({"id": event["Test"], "status": event["Action"]})
        if not rows:
            errors.append("no_per_test_runtime_evidence")
    if any(not row.get("id") for row in rows):
        errors.append("missing_runtime_test_id")
    if any(row["status"] == "error" for row in rows):
        errors.append("test_setup_or_runtime_error")
    return rows, sorted(set(errors)), used


def matches_runtime(actual: str, requested: str) -> bool:
    local = actual.rsplit("::", 1)[-1]
    return any(value == requested or value.startswith(requested + "[") or value.startswith(requested + "/")
               for value in (actual, local))


def load_runs(path: Path | None) -> tuple[list[dict], list[dict]]:
    if path is None:
        return [], []
    document = read(path)
    records = document if isinstance(document, list) else document["runs"]
    # Emitters share one original control across several generated obligations.
    # Bind those controls through declared control IDs, never by filename alone.
    expanded = []
    for record in records:
        if record["role"] == "control" and not record.get("candidate_id"):
            for generated in records:
                if (generated["role"] == "generated" and generated["case"] == record["case"]
                        and set(record.get("test_ids", [])) & set(generated.get("control_ids", []))):
                    expanded.append({**record, "candidate_id": generated["candidate_id"],
                                     "association": "generated.control_ids"})
        else:
            expanded.append(record)
    records = expanded
    result, frozen, cached_results, cached_manifests = [], [freeze_file(path)], {}, set()
    for record in records:
        if record["role"] not in {"generated", "control"}:
            raise ValueError("Only generated and source-control candidate runs are accepted")
        file = Path(record["result"])
        file = file if file.is_absolute() else path.parent / file
        if record.get("result_sha256") and digest(file) != record["result_sha256"]:
            raise ValueError("Declared run result hash differs")
        if file not in cached_results:
            cached_results[file] = runtime_tests(file)
        tests, errors, used = cached_results[file]
        errors = list(errors)
        frozen.extend(freeze_file(p) for p in used)
        if record.get("manifest") and record["manifest"] not in cached_manifests:
            manifest_path = Path(record["manifest"])
            manifest_path = manifest_path if manifest_path.is_absolute() else path.parent / manifest_path
            emitted = read(manifest_path)
            frozen.append(freeze_file(manifest_path))
            for mount in emitted.get("mounts", []):
                source = Path(mount["source"])
                if digest(source) != mount["sha256"]:
                    raise ValueError("Emitted source no longer matches executed manifest")
                frozen.append(freeze_file(source))
            cached_manifests.add(record["manifest"])
        requested = record.get("test_ids", [])
        selected = [t for t in tests if any(matches_runtime(t["id"], name) for name in requested)]
        missing = [name for name in requested if not any(matches_runtime(t["id"], name) for t in tests)]
        if not requested:
            errors.append("no_declared_test_ids")
        if missing:
            errors.append("declared_tests_not_observed")
        result.append({**record, "result": str(file.resolve()), "tests": selected,
                       "errors": sorted(set(errors)), "missing": missing,
                       "passed": bool(selected) and not errors and all(t["status"] == "pass" for t in selected),
                       "failed": any(t["status"] == "fail" for t in selected) and not errors})
    return result, list({record["path"]: record for record in frozen}.values())


def inventory(args) -> dict:
    census = read(args.census)
    entries, prepared_files = load_batches(args, census)
    runs, run_files = load_runs(args.runs)
    keys = {(e["case"], e["candidate_id"]) for e in entries}
    orphan = [r for r in runs if (r["case"], r["candidate_id"]) not in keys]
    if orphan:
        raise ValueError("Execution index contains candidates absent from the frozen batch")
    for entry in entries:
        entry["review"] = {dimension: {"verdict": "unknown", "reason": "", "evidence": []}
                           for dimension in DIMENSIONS}
    return {"version": VERSION, "role": "independent_review_template",
            "census": freeze_file(args.census), "batch_root": str(args.batch_root.resolve()),
            "frozen_files": prepared_files + run_files, "runs": runs, "runs_sha256": canonical(runs), "candidates": entries,
            "review_instructions": "For each yes/no supply an independent reason and evidence [{path,sha256}]. Do not infer scenario/oracle/target cause from source-parent hit or exit status."}


def reviewed(field: dict) -> bool | None:
    verdict = field.get("verdict", "unknown")
    if verdict not in {"yes", "no", "unknown"}:
        raise ValueError("Review verdict must be yes, no, or unknown")
    if verdict == "unknown":
        return None
    if not field.get("reason") or not field.get("evidence"):
        raise ValueError("A semantic verdict requires an independent reason and evidence")
    for evidence in field["evidence"]:
        verify_file(evidence)
    return verdict == "yes"


def evaluate(args) -> dict:
    review = read(args.reviews)
    if canonical(review["runs"]) != review["runs_sha256"]:
        raise ValueError("Frozen execution index was edited in review template")
    verify_file(review["census"])
    for file in review["frozen_files"]:
        verify_file(file)
    census = read(Path(review["census"]["path"]))
    entries, _ = load_batches(args, census)
    fresh = {(e["case"], e["candidate_id"]): e for e in entries}
    verdicts, keys = [], set()
    for row in review["candidates"]:
        key = row["case"], row["candidate_id"]
        if key in keys or key not in fresh or row["candidate_sha256"] != fresh[key]["candidate_sha256"]:
            raise ValueError("Review candidate differs from frozen batch")
        keys.add(key)
        related = [r for r in review["runs"] if (r["case"], r["candidate_id"]) == key]
        controls = [r for r in related if r["role"] == "control"]
        generated = [r for r in related if r["role"] == "generated"]
        # Reparse source result files; edited template run booleans are not trusted.
        def recheck(run):
            tests, errors, _ = runtime_tests(Path(run["result"]))
            requested = run.get("test_ids", [])
            selected = [t for t in tests if any(matches_runtime(t["id"], n) for n in requested)]
            observed = requested and all(any(matches_runtime(t["id"], n) for t in tests) for n in requested)
            return bool(observed and selected and not errors and all(t["status"] == "pass" for t in selected)), bool(observed and not errors and any(t["status"] == "fail" for t in selected))
        control_pass = bool(controls) and all(recheck(r)[0] for r in controls)
        raw_failure = any(recheck(r)[1] for r in generated)
        semantic = {name: reviewed(row["review"][name]) for name in DIMENSIONS}
        detected = control_pass and raw_failure and all(v is True for v in semantic.values())
        result = {**fresh[key], **semantic, "control_pass": control_pass,
                  "generated_test_failure": raw_failure, "target_gap_detected": detected,
                  "controlled_failure": control_pass and raw_failure,
                  "confirmed_false_alarm": control_pass and raw_failure and semantic["correct_oracle"] is False,
                  "unresolved_controlled_failure": control_pass and raw_failure and semantic["correct_oracle"] is None,
                  "all_dimensions_proven": detected and fresh[key]["test_hit"],
                  "generated_runs": len(generated), "control_runs": len(controls)}
        verdicts.append(result)
    if keys != set(fresh):
        raise ValueError("Review must account for every frozen candidate, including unknowns")
    cases = []
    for target in census["cases"]:
        rows = [r for r in verdicts if r["case"] == target["case"]]
        cases.append({"case": target["case"], "candidate_count": len(rows),
                      "retrieval_test_hit": any(r["selected_target_ids"] for r in rows),
                      "test_hit": any(r["test_hit"] for r in rows),
                      "scenario_hit": any(r["scenario_hit"] is True for r in rows),
                      "correct_oracle_on_target_scenario": any(r["scenario_hit"] is True and r["correct_oracle"] is True for r in rows),
                      "target_gap_detected": any(r["target_gap_detected"] for r in rows),
                      "all_dimensions_proven": any(r["all_dimensions_proven"] for r in rows),
                      "detected_candidate_ids": [r["candidate_id"] for r in rows if r["target_gap_detected"]]})
    dimensions = ("retrieval_test_hit", "test_hit", "scenario_hit", "correct_oracle_on_target_scenario", "target_gap_detected", "all_dimensions_proven")
    return {"version": VERSION, "census_sha256": review["census"]["sha256"],
            "reviews_sha256": digest(args.reviews), "denominator": len(cases),
            "counts": {name: sum(row[name] for row in cases) for name in dimensions},
            "candidate_outcome_counts": {name: sum(row[name] for row in verdicts) for name in
                ("generated_test_failure", "controlled_failure", "confirmed_false_alarm", "unresolved_controlled_failure")},
            "all_17_targets_proven": len(cases) == 17 and all(r["all_dimensions_proven"] for r in cases),
            "cases": cases, "candidates": verdicts,
            "scope": "Development/discovery set; missing evidence remains unverified. Fixed-parent hit is reported separately from genuine detection through an alternative valid source test."}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=("inventory", "evaluate"))
    parser.add_argument("--batch-root", type=Path, required=True)
    parser.add_argument("--additional-batch-root", type=Path, action="append", default=[])
    parser.add_argument("--census", type=Path, default=DEFAULT_CENSUS)
    parser.add_argument("--runs", type=Path)
    parser.add_argument("--reviews", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.stage == "evaluate" and not args.reviews:
        parser.error("evaluate requires --reviews")
    result = inventory(args) if args.stage == "inventory" else evaluate(args)
    write_new(args.output, result)
    print(json.dumps({"output": str(args.output), "candidates": len(result.get("candidates", [])),
                      "counts": result.get("counts"), "all_17_targets_proven": result.get("all_17_targets_proven", False)}))


if __name__ == "__main__":
    main()
