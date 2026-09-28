"""Uniform finite source-only semantic/execution batch; no evaluator imports.

Each available prepared case receives its protocol's at most two requests.
There are no automatic provider retries and no outcome-based reselection.
Docker runs use a shared two-container semaphore, one worker per case run.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import threading
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
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--preparation-timeout", type=int, default=2400)
    args = parser.parse_args()
    if not 1 <= args.workers <= 4:
        parser.error("Provider concurrency must be between one and four")
    ledger = Path(str(args.prefix) + "_pipeline")
    ledger.mkdir(parents=True, exist_ok=False)
    code = [ROOT / p for p in ("relational_gap/semantics.py", "relational_gap/semantics_v2.py", "relational_gap/provider.py",
                               "scripts/execute_relational_gap.py", "generic_composition/emitter.py")]
    hashes = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in code}
    write(ledger / "frozen_driver.json", {"files_sha256": hashes, "provider_concurrency": args.workers,
                                         "docker_concurrency": 2, "automatic_retries": 0})
    for file in code:
        dest = ledger / "driver_snapshot" / file.relative_to(ROOT)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(file.read_bytes())
    docker_slots = threading.Semaphore(2)
    started = time.monotonic()
    cases = [row["id"] for row in read(args.registry)]

    def stage(case, name, command):
        # Request/validation behavior stays frozen even while future static
        # analysis batches are developed in the shared repository.
        for path, expected in hashes.items():
            if hashlib.sha256((ROOT / path).read_bytes()).hexdigest() != expected:
                raise RuntimeError("frozen_pipeline_code_changed:" + path)
        process = subprocess.run([sys.executable, str(ROOT / "scripts/execute_relational_gap.py"), *command],
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

    def execute(case):
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
                summary["stages"]["complete_" + index] = stage(case, "complete_" + index,
                    ["complete", "--input", str(semantic), "--index", index, "--output", str(destination)])
                if (destination / "validation.json").exists():
                    validations.append(str(destination))
            summary["stages"]["emit"] = stage(case, "emit", ["emit", "--input", str(source), "--output", str(emitted), "--completions", *validations])
            with docker_slots:
                summary["stages"]["run"] = stage(case, "run", ["run", "--input", str(emitted), "--output", str(executed), "--workers", "1", "--registry", str(args.registry)])
            summary["status"] = "complete"
        except Exception as error:
            summary.update(status="pipeline_error", error_type=type(error).__name__, error=str(error))
        write(ledger / case / "summary.json", summary)
        return summary

    summaries = []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        pending = {pool.submit(execute, case): case for case in cases}
        for future in as_completed(pending):
            result = future.result()
            summaries.append(result)
            write(ledger / "summary.json", summaries)
            print(json.dumps({"case": result["case"], "status": result["status"]}), flush=True)
    runs = []
    for case in cases:
        file = Path(str(args.prefix) + "_runs") / case / "runs.json"
        if file.exists():
            runs.extend(read(file))
    write(ledger / "runs.json", runs)
    print(json.dumps({"finished_cases": len(summaries), "runs": len(runs), "ledger": str(ledger)}), flush=True)


if __name__ == "__main__":
    main()
