"""Uniform finite source-only semantic/execution batch; no evaluator imports.

Each available prepared case receives its protocol's at most two requests.
There are no automatic provider retries and no outcome-based reselection.
A separate two-worker Docker queue runs one container per case worker.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n")


def read(path):
    return json.loads(path.read_text())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch-root", type=Path, required=True)
    parser.add_argument("--prefix", type=Path, required=True)
    parser.add_argument("--fallback-batch-root", type=Path)
    parser.add_argument("--registry", type=Path, default=ROOT / "data/relational_gap_v1/registry.json")
    parser.add_argument("--dependency-packages-root", type=Path,
                        default=ROOT / "data/relational_gap_v1_dependency_packages")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--preparation-timeout", type=int, default=2400)
    args = parser.parse_args()
    if not 1 <= args.workers <= 4:
        parser.error("Provider concurrency must be between one and four")
    ledger = Path(str(args.prefix) + "_pipeline")
    ledger.mkdir(parents=True, exist_ok=False)
    code = [ROOT / p for p in ("relational_gap/semantics.py", "relational_gap/semantics_v2.py", "relational_gap/provider.py", "relational_gap/source_expected_values.py",
                               "scripts/execute_relational_gap_v6.py", "scripts/relational_execution_lanes.py", "combination_testing/runner.py", "scripts/go_materialization.py", "scripts/go_history_dependencies_v6.py", "scripts/go_dependency_import_aliases.py",
                               "scripts/go_source_materializer/main.go", "scripts/relational_phase_runner.py", "scripts/run_relational_gap_batch_v6.py",
                               "scripts/run_relational_gap_case.py", "vendor/replay/container_replay.py",
                               "generic_composition/emitter.py", "generic_composition/runner.py",
                               "generic_composition/corpus.py", "combination_testing/test_reports.py")]
    code.extend(ROOT / p for p in ("anchor_retrieval/syntax.py", "anchor_retrieval/frontier.py",
                                   "anchor_retrieval/index.py", "anchor_retrieval/graph.py",
                                   "experimental/semantic_transport/oracle.py",
                                   "experimental/semantic_transport/expected_templates.py"))
    hashes = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in code}
    dependency_files = sorted(args.dependency_packages_root.glob('*.json'))
    dependency_hashes = {str(p.resolve()): hashlib.sha256(p.read_bytes()).hexdigest()
                         for p in dependency_files if not p.stem.endswith('_requests')}
    write(ledger / "frozen_driver.json", {"files_sha256": hashes, "provider_concurrency": args.workers,
                                         "dependency_package_inventories_sha256": dependency_hashes,
                                         "docker_concurrency": 2, "automatic_retries": 0,
                                         "execution_budget": {"source_q": 128, "llm_q": 64, "total": 192},
                                         "model_budget_unchanged": True, "execution_budget_increased": True})
    for file in code:
        dest = ledger / "driver_snapshot" / file.relative_to(ROOT)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(file.read_bytes())
    for file in dependency_hashes:
        dest = ledger / 'dependency_package_snapshots' / Path(file).name
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(Path(file).read_bytes())
    started = time.monotonic()
    cases = [row["id"] for row in read(args.registry)]

    def stage(case, name, command):
        # Request/validation behavior stays frozen even while future static
        # analysis batches are developed in the shared repository.
        for path, expected in hashes.items():
            if hashlib.sha256((ROOT / path).read_bytes()).hexdigest() != expected:
                raise RuntimeError("frozen_pipeline_code_changed:" + path)
        for path, expected in dependency_hashes.items():
            if hashlib.sha256(Path(path).read_bytes()).hexdigest() != expected:
                raise RuntimeError('frozen_dependency_package_inventory_changed:' + path)
        process = subprocess.run([sys.executable, str(ROOT / "scripts/execute_relational_gap_v6.py"), *command],
                                 cwd=ROOT, capture_output=True, text=True)
        out = ledger / case
        out.mkdir(parents=True, exist_ok=True)
        (out / (name + ".stdout")).write_text(process.stdout)
        (out / (name + ".stderr")).write_text(process.stderr)
        if process.returncode:
            raise RuntimeError("stage_failed:" + name)
        summary = json.loads(process.stdout.strip().splitlines()[-1]) if process.stdout.strip() else {}
        print(json.dumps({"case": case, "stage": name, "summary": summary}), flush=True)
        return summary

    def prepare_complete_emit(case):
        source = args.batch_root / case
        while not (source / "prepare.json").exists():
            fallback = args.fallback_batch_root / case if args.fallback_batch_root else None
            if fallback is not None and (fallback / "prepare.json").exists():
                source = fallback
                break
            if time.monotonic() - started > args.preparation_timeout:
                return {"case": case, "status": "preparation_not_available"}
            time.sleep(2)
        semantic = Path(str(args.prefix) + "_semantics") / case
        completed = Path(str(args.prefix) + "_completions") / case
        emitted = Path(str(args.prefix) + "_emitted") / case
        executed = Path(str(args.prefix) + "_runs") / case
        summary = {"case": case, "stages": {}}
        try:
            summary["stages"]["requests"] = stage(case, "requests", ["requests", "--input", str(source), "--output", str(semantic)])
            requests = sorted(semantic.glob("request_*.json"))
            if len(requests) > 2:
                raise RuntimeError("more_than_two_requests_in_frozen_protocol")
            validations = []
            for path in requests:
                index = path.stem.rsplit("_", 1)[-1]
                destination = completed / ("r" + index)
                try:
                    summary["stages"]["complete_" + index] = stage(case, "complete_" + index,
                        ["complete", "--input", str(semantic), "--index", index, "--output", str(destination)])
                except Exception as error:
                    # A provider/decoder error cannot remove the exact source
                    # hypotheses already frozen in this request. Stage stderr
                    # remains persisted, and there is no retry.
                    summary["stages"]["complete_" + index] = {
                        "status": "model_stage_error_source_lane_retained",
                        "error_type": type(error).__name__, "error": str(error)}
                if (destination / "validation.json").exists():
                    validations.append(str(destination))
            summary["stages"]["emit"] = stage(case, "emit", ["emit", "--input", str(source), "--output", str(emitted), "--semantics", str(semantic), "--dependency-packages-root", str(args.dependency_packages_root), "--completions", *validations])
            summary["status"] = "ready_for_execution"
            summary["emitted"] = str(emitted)
            summary["executed"] = str(executed)
        except Exception as error:
            summary.update(status="pipeline_error", error_type=type(error).__name__, error=str(error))
        write(ledger / case / "summary.json", summary)
        return summary

    def execute_emitted(summary):
        case = summary["case"]
        try:
            summary["stages"]["run"] = stage(case, "run", ["run", "--input", summary["emitted"],
                "--output", summary["executed"], "--workers", "1", "--registry", str(args.registry)])
            summary["status"] = "complete"
        except Exception as error:
            summary.update(status="pipeline_error", error_type=type(error).__name__, error=str(error))
        write(ledger / case / "summary.json", summary)
        return summary

    summaries = []
    def finished(result):
        summaries.append(result)
        write(ledger / "summary.json", summaries)
        print(json.dumps({"case": result["case"], "status": result["status"]}), flush=True)

    # Provider and Docker queues have separate finite resource bounds. A slow
    # test cannot prevent later cases from receiving their uniform model budget.
    with ThreadPoolExecutor(max_workers=2) as executions:
        run_futures = {}
        with ThreadPoolExecutor(max_workers=args.workers) as providers:
            pending = {providers.submit(prepare_complete_emit, case): case for case in cases}
            for future in as_completed(pending):
                result = future.result()
                if result["status"] == "ready_for_execution":
                    run_futures[executions.submit(execute_emitted, result)] = result["case"]
                else:
                    finished(result)
        print(json.dumps({"provider_phase_complete": True, "queued_execution_cases": len(run_futures)}), flush=True)
        for future in as_completed(run_futures):
            finished(future.result())
    runs = []
    for case in cases:
        file = Path(str(args.prefix) + "_runs") / case / "runs.json"
        if file.exists():
            runs.extend(read(file))
    write(ledger / "runs.json", runs)
    print(json.dumps({"finished_cases": len(summaries), "runs": len(runs), "ledger": str(ledger)}), flush=True)


if __name__ == "__main__":
    main()
