"""Run inside the official task image with candidate artifacts mounted read-only.

Usage: python replay_mnamer_combination_cli.py /evidence/model.patch
Produces JSON; executes the candidate CLI in fresh temporary directories.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import os
import subprocess
import sys
import tempfile


def main() -> None:
    patch = Path(sys.argv[1])
    base = subprocess.check_output(["git", "-c", "safe.directory=/app", "rev-parse", "HEAD"], cwd="/app", text=True).strip()
    assert base == "73f5b537c8cad998e8e6d6bc40ad60e2e23bf268", base
    subprocess.run(["git", "-c", "safe.directory=/app", "apply", str(patch)], cwd="/app", check=True)
    records = []
    for duplicate, quota in [(False, None), (False, 2), (True, None), (True, 2)]:
        with tempfile.TemporaryDirectory(prefix="mnamer-cli-combination-") as tmp:
            folder = Path(tmp)
            watch = folder / "Downloads"
            watch.mkdir()
            for n in range(5):
                (watch / f"movie.{n:02d}.mp4").write_bytes(b"x" * 10)
            args = [sys.executable, "-m", "mnamer", "--daemon-run-once", "--watch", "Downloads",
                    "--daemon-state", "daemon-state.json", "--stability-interval-ms", "50",
                    "--stability-checks", "1"]
            if quota is not None:
                args.extend(["--batch-size", str(quota)])
            args.extend(["--batch", "--movie-directory", "Movies"])
            if duplicate:
                args.append("Downloads")
            env = dict(os.environ, PYTHONPATH="/app")
            completed = subprocess.run(args, cwd=folder, env=env, capture_output=True, text=True, timeout=30)
            moved = sorted(path.name for path in (folder / "Movies").glob("*.mp4"))
            expected = 5 if quota is None else quota
            records.append({"duplicate_watch_and_positional": duplicate, "batch_size": quota,
                            "command": args, "returncode": completed.returncode,
                            "stdout": completed.stdout, "stderr": completed.stderr,
                            "moved": moved, "actual_count": len(moved), "expected_count": expected,
                            "passed": completed.returncode == 0 and len(moved) == expected})
    print(json.dumps({"base_commit": base, "candidate_patch_sha256": hashlib.sha256(patch.read_bytes()).hexdigest(),
                      "scope": "official task image; candidate patch; full real CLI; four independent scenarios; no reference patch or verifier test installed",
                      "results": records}, ensure_ascii=False, indent=2))
    assert [row["passed"] for row in records] == [True, True, True, False]


if __name__ == "__main__":
    main()
