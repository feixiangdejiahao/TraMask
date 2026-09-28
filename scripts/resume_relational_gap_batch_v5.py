"""Resume missing v5 stages without retrying any persisted provider attempt."""
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "results/relational_gap_20260928"
PREFIX = BASE / "batch5"
LEDGER = BASE / "batch5_resume_pipeline"


def read(path):
    return json.loads(path.read_text())


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n")


def main():
    offline_only = "--execution-only" in sys.argv
    LEDGER.mkdir(exist_ok=False)
    hashes = read(BASE / "batch5_pipeline/frozen_driver.json")["files_sha256"]
    def verify():
        for name, expected in hashes.items():
            if hashlib.sha256((ROOT / name).read_bytes()).hexdigest() != expected:
                raise ValueError("Frozen driver changed: " + name)
    verify()
    write(LEDGER / "manifest.json", {"started_utc": datetime.now(timezone.utc).isoformat(),
          "source": str(Path(__file__).resolve()), "source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
          "frozen_driver_sha256": hashlib.sha256((BASE / "batch5_pipeline/frozen_driver.json").read_bytes()).hexdigest(),
          "provider_retries": 0, "docker_concurrency": 2,
          "execution_only": offline_only,
          "reason": "Original tool process disappeared; continue only previously absent stages."})
    (LEDGER / "source_snapshot.py").write_bytes(Path(__file__).read_bytes())
    def stage(case, name, arguments):
        verify()
        result = subprocess.run([sys.executable, str(ROOT / "scripts/execute_relational_gap_v5.py"), *arguments],
                                cwd=ROOT, text=True, capture_output=True)
        folder = LEDGER / case
        folder.mkdir(exist_ok=True)
        (folder / (name + ".stdout")).write_text(result.stdout)
        (folder / (name + ".stderr")).write_text(result.stderr)
        if result.returncode:
            raise RuntimeError("stage_failed:" + case + ":" + name)
        summary = json.loads(result.stdout.strip().splitlines()[-1]) if result.stdout.strip() else {}
        print(json.dumps({"case": case, "stage": name,
                          "summary": {key: value for key, value in summary.items() if key != "outcomes"}}), flush=True)
        return summary
    def prepare(case):
        source = PREFIX / case
        semantic = BASE / "batch5_semantics" / case
        completions = BASE / "batch5_completions" / case
        emitted = BASE / "batch5_emitted" / case
        if not (source / "prepare.json").exists():
            raise ValueError("Prepared source missing:" + case)
        if not semantic.exists():
            stage(case, "requests", ["requests", "--input", str(source), "--output", str(semantic)])
        requests = sorted(semantic.glob("request_*.json"))
        if len(requests) > 2:
            raise ValueError("Request budget exceeded")
        valid = []
        for request in requests:
            index = request.stem.rsplit("_", 1)[1]
            output = completions / ("r" + index)
            if not output.exists():
                try:
                    stage(case, "complete_" + index, ["complete", "--input", str(semantic),
                          "--index", index, "--output", str(output)])
                except RuntimeError as error:
                    write(LEDGER / case / ("model_error_" + index + ".json"), {"error": str(error), "source_lane_retained": True})
            if (output / "validation.json").exists():
                valid.append(str(output))
        if not emitted.exists():
            stage(case, "emit", ["emit", "--input", str(source), "--output", str(emitted),
                                  "--semantics", str(semantic), "--completions", *valid])
        if not (emitted / "artifacts.json").exists():
            raise RuntimeError("Partial emission preserved; no automatic overwrite:" + case)
        return case
    def execute(case):
        emitted, output = BASE / "batch5_emitted" / case, BASE / "batch5_runs" / case
        if not output.exists():
            stage(case, "run", ["run", "--input", str(emitted), "--output", str(output), "--workers", "1"])
            status = "continued_missing_execution"
        else:
            expected = {Path(x).name for x in read(emitted / "artifacts.json")}
            summary = read(output / "summary.json") if (output / "summary.json").exists() else []
            completed = {Path(x["artifact"]).name for x in summary}
            if completed != expected:
                raise RuntimeError("Partial execution preserved; no automatic retry:" + case)
            status = "reused_completed_execution"
        write(LEDGER / case / "summary.json", {"case": case, "status": status})
        print(json.dumps({"case": case, "status": status}), flush=True)
    cases = [row["id"] for row in read(ROOT / "data/relational_gap_v1/registry.json")]
    if offline_only:
        available = [case for case in cases if (BASE / "batch5_emitted" / case / "artifacts.json").exists()]
        with ThreadPoolExecutor(max_workers=2) as executions:
            for future in as_completed([executions.submit(execute, case) for case in available]):
                future.result()
        verify()
        runs = [row for case in available for row in read(BASE / "batch5_runs" / case / "runs.json")]
        write(LEDGER / "runs_existing.json", runs)
        write(LEDGER / "summary.json", {"completed_cases": len(available), "runs": len(runs),
                                      "missing_emitted_cases": [case for case in cases if case not in available],
                                      "provider_calls": 0, "frozen_driver_hashes_valid": True})
        print(json.dumps({"completed_cases": len(available), "runs": len(runs), "provider_calls": 0}), flush=True)
        return
    with ThreadPoolExecutor(max_workers=2) as executions:
        pending = []
        with ThreadPoolExecutor(max_workers=4) as providers:
            for future in as_completed([providers.submit(prepare, case) for case in cases]):
                pending.append(executions.submit(execute, future.result()))
        for future in as_completed(pending):
            future.result()
    verify()
    runs = [row for case in cases for row in read(BASE / "batch5_runs" / case / "runs.json")]
    destination = BASE / "batch5_pipeline/runs.json"
    if destination.exists():
        raise RuntimeError("Refusing to overwrite existing final execution index")
    write(destination, runs)
    write(LEDGER / "summary.json", {"completed_cases": len(cases), "runs": len(runs), "frozen_driver_hashes_valid": True})
    print(json.dumps({"completed_cases": len(cases), "runs": len(runs)}), flush=True)


if __name__ == "__main__":
    main()
