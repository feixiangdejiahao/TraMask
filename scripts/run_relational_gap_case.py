"""Run ordinary generated tests on a fresh exact candidate, offline in Docker.

This execution adapter has no oracle, target-test names, or per-case transform.
The caller supplies the command and optional test-file mounts. A nonzero test
exit is recorded separately from environment/transport failures.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shlex
import subprocess
import time

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "results/relational_gap_20260928/case_registry.json"


def run_case(case_id: str, command: str, *, mounts: list[dict] | None = None,
             timeout: int = 180, output: Path | None = None, registry: Path = REGISTRY) -> dict:
    record = next(row for row in json.loads(registry.read_text()) if row["id"] == case_id)
    out = output or ROOT / "results/relational_gap_20260928/execution" / case_id / str(time.time_ns())
    out.mkdir(parents=True, exist_ok=False)
    request = {"program": "candidate", "command": command, "language": record["language"],
               "coverage": False, "timeout": timeout, "uid": os.getuid(), "gid": os.getgid()}
    docker = ["docker", "run", "--rm", "--interactive", "--init", "--network", "none",
              "--cpus", "2", "--memory", "8g", "--pull", "never",
              "--mount", f"type=bind,src={ROOT / 'vendor/replay/container_replay.py'},dst=/replay.py,readonly",
              "--mount", f"type=bind,src={out.resolve()},dst=/replay-logs",
              "--mount", f"type=bind,src={record['candidate_patch']},dst=/candidate.patch,readonly"]
    mounted = []
    setup = []
    for index, entry in enumerate(mounts or []):
        source = Path(entry["source"]).resolve()
        relative = Path(entry["target"])
        if relative.is_absolute() or ".." in relative.parts or not source.is_file():
            raise ValueError("Test mounts require an existing file and a repository-relative target")
        # Copy after applying the patch: direct mounts over a changed existing
        # file would prevent git apply from modifying that file.
        docker += ["--mount", f"type=bind,src={source},dst=/relational-inputs/{index},readonly"]
        setup.append(f"mkdir -p {shlex.quote(str(Path('/app') / relative.parent))}")
        setup.append(f"cp /relational-inputs/{index} {shlex.quote(str(Path('/app') / relative))}")
        mounted.append({"source": str(source), "target": str(relative),
                        "sha256": hashlib.sha256(source.read_bytes()).hexdigest()})
    if setup:
        request["command"] = "set -e\n" + "\n".join(setup) + "\n" + command
    container_name = "relational-gap-" + case_id.lower() + "-" + str(time.time_ns())
    docker += ["--name", container_name, "--entrypoint", "python3", record["image"], "/replay.py"]
    manifest = {"case": case_id, "image": record["image"], "image_id": record.get("image_id"),
                "expected_base_commit": record["base_commit"], "request": request, "mounts": mounted,
                "candidate_patch_sha256": hashlib.sha256(Path(record["candidate_patch"]).read_bytes()).hexdigest(),
                "docker_command": docker, "verifier_or_reference_mounted": False}
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    try:
        execution = subprocess.run(docker, input=json.dumps(request), text=True, capture_output=True, timeout=timeout + 120)
        (out / "transport.stdout").write_text(execution.stdout)
        (out / "transport.stderr").write_text(execution.stderr)
        result = json.loads((out / "result.json").read_text()) if (out / "result.json").exists() else {"error": "container produced no result"}
        result.update(transport_returncode=execution.returncode, output=str(out))
    except subprocess.TimeoutExpired as error:
        subprocess.run(["docker", "rm", "-f", container_name], capture_output=True)
        result = {"error": "transport_timeout", "detail": str(error), "output": str(out)}
    (out / "execution.json").write_text(json.dumps(result, indent=2) + "\n")
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", required=True)
    parser.add_argument("--command", required=True)
    parser.add_argument("--test-file", type=Path)
    parser.add_argument("--target")
    parser.add_argument("--mounts", type=Path, help="JSON list with source and repository-relative target")
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--registry", type=Path, default=REGISTRY)
    args = parser.parse_args()
    mounts = json.loads(args.mounts.read_text()) if args.mounts else []
    if bool(args.test_file) != bool(args.target):
        parser.error("--test-file and --target must be supplied together")
    if args.test_file:
        mounts.append({"source": str(args.test_file), "target": args.target})
    result = run_case(args.case, args.command, mounts=mounts, timeout=args.timeout, output=args.output, registry=args.registry)
    print(json.dumps(result, indent=2))
    raise SystemExit(2 if "error" in result else 0)


if __name__ == "__main__":
    main()
