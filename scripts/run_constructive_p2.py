"""Reproduce the small P2 demonstrations in copied repositories/offline images.

Usage: python3 scripts/run_constructive_p2.py RUN_DIRECTORY [T13 T17 T25 T29]
Requires Go and locally cached Docker task images. Does not install packages.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
ORIGINAL = ROOT / "results/behavioral_gap_augmentation/20261007_relation_v1_n30_r01"
TRIALS = ROOT / "results/failure_analysis/deepswe_failed_trials_n211_20261006/trials"


def record(command, cwd, directory, env=None):
    directory.mkdir(parents=True, exist_ok=True)
    start = time.time()
    try:
        result = subprocess.run(command, cwd=cwd, env=env, capture_output=True, text=True, timeout=240)
        code, stdout, stderr = result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired as err:
        code = 124
        stdout = err.stdout or b""
        stderr = err.stderr or b""
        if isinstance(stdout, bytes): stdout = stdout.decode(errors="replace")
        if isinstance(stderr, bytes): stderr = stderr.decode(errors="replace")
        stderr += "\nP2 runner timeout after 240 seconds\n"
    (directory / "stdout.log").write_text(stdout)
    (directory / "stderr.log").write_text(stderr)
    data = {"argv": command, "cwd": str(cwd), "exit_code": code,
            "elapsed_seconds": round(time.time() - start, 3)}
    (directory / "execution.json").write_text(json.dumps(data, indent=2) + "\n")
    print(json.dumps({"run": str(directory.relative_to(ROOT)), **data}), flush=True)


def main():
    run = Path(sys.argv[1]).resolve()
    selected = sys.argv[2:] or ["T13", "T25", "T29"]
    run.mkdir(parents=True, exist_ok=True)
    generated = run / "generated"
    inputs = run / "inputs"
    inputs.mkdir(exist_ok=True)
    shutil.copy2(ROOT / "src/constructive_p2.py", inputs / "constructive_p2.py")
    shutil.copy2(Path(__file__), inputs / "run_constructive_p2.py")
    subprocess.run([sys.executable, str(ROOT / "src/constructive_p2.py"), str(generated)], check=True)
    protocol = ROOT / "research/constructive_abstraction_20261021/protocol.json"
    shutil.copy2(protocol, run / "protocol.json")
    cases = {c["id"]: c for c in json.loads((ORIGINAL / "cases.json").read_text())}
    for case_id in selected:
        case = cases[case_id]
        case_dir = run / "cases" / case_id
        case_dir.mkdir(parents=True, exist_ok=True)
        source = ORIGINAL / "cases" / case_id / "repository"
        receipts = []
        for name in ("instruction.md", "model.patch", "trajectory.json"):
            path = TRIALS / case["trial"] / name
            receipts.append({"path": str(path.relative_to(ROOT)), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
        (case_dir / "inputs.json").write_text(json.dumps({"case": case_id, "trial": case["trial"],
            "repository": str(source.relative_to(ROOT)), "image": case["image"], "receipts": receipts}, indent=2) + "\n")
        if case_id in ("T13", "T17"):
            repo = case_dir / "repository"
            shutil.copytree(source, repo, ignore=shutil.ignore_patterns(".git", "node_modules", ".env"))
            env = dict(os.environ, GOCACHE=str(run / "go-cache"), GOPROXY="off", GOSUMDB="off")
            baseline = "^TestCompiledFunctionCall" if case_id == "T13" else "^TestDestructuring"
            test_name = "^TestP2Alias$" if case_id == "T13" else "^TestP2Presence$"
            filename = "p2_alias_test.go" if case_id == "T13" else "p2_presence_test.go"
            record(["go", "test", "-count=1", "-v", "-run", baseline, "."], repo, case_dir / "baseline", env)
            shutil.copy2(generated / filename, repo / filename)
            record(["go", "test", "-count=1", "-v", "-run", test_name, "."], repo, case_dir / "generated", env)
        else:
            # Mount both repositories and generated tests read-only. All code
            # overlay and dependency use occur inside disposable containers.
            docker = ["docker", "run", "--rm", "--network", "none",
                      "--mount", f"type=bind,src={source},dst=/input,readonly",
                      "--mount", f"type=bind,src={generated},dst=/generated,readonly",
                      "--entrypoint", "sh", case["image"], "-c"]
            overlay = "cp -a /input/. /app/ && "
            if case_id == "T25":
                base = overlay + "cd /app && ./node_modules/.bin/vitest run --threads false"
                gen = (overlay + "cp /generated/p2-alias.test.ts /app/src/p2-alias.test.ts && "
                       "cd /app && ./node_modules/.bin/vitest run src/p2-alias.test.ts --threads false")
            else:
                base = (overlay + "cd /app/packages/core && "
                        "./node_modules/.bin/vitest run tests/predicate.test.ts --maxWorkers 1")
                gen = (overlay + "cp /generated/p2-fresh.test.ts /app/packages/core/tests/p2-fresh.test.ts && "
                       "cd /app/packages/core && ./node_modules/.bin/vitest run tests/p2-fresh.test.ts --maxWorkers 1")
            record(docker + [base], ROOT, case_dir / "baseline")
            record(docker + [gen], ROOT, case_dir / "generated")


if __name__ == "__main__":
    main()
