"""Prepare a frozen, outcome-blind selection without evaluator assets.

Only task metadata, instruction.md, trajectory.json and the submitted model.patch
are copied. No task tests/, solution/, verifier or historical outcome is read.
Repository contents are copied opaquely; preparation does not inspect their code.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import io
import json
from pathlib import Path
import subprocess
import tarfile
import tomllib

import httpx

ROOT = Path(__file__).resolve().parents[1]
SELECTION = ROOT / "research/generic_holdout_selection_v1.json"
TASKS = Path("/home/jhx/oracle_gap/external/deep-swe/tasks")
DEST = ROOT / "data/generic_holdout_v1"


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def run(*args: str, **kwargs):
    return subprocess.run(args, check=True, capture_output=True, **kwargs)


def acquire(item: dict) -> dict:
    case_dir = DEST / item["id"]
    case_dir.mkdir(parents=True, exist_ok=True)
    task = TASKS / item["id"]
    config = tomllib.loads((task / "task.toml").read_text())
    image = config["environment"]["docker_image"]
    record = {**item, "image": image, "artifacts": []}
    instruction = (task / "instruction.md").read_bytes()
    (case_dir / "issue.md").write_bytes(instruction)
    record["artifacts"].append({"path": "issue.md", "sha256": digest(instruction), "source": str(task / "instruction.md")})
    trial = item["trial"]["trial_name"]
    base = f"https://d3ujjcmjq6o8v6.cloudfront.net/v1.1/trial-artifacts/{trial}"
    for name, relative in (("trajectory.json", "agent/trajectory.json"), ("model.patch", "artifacts/model.patch")):
        path = case_dir / name
        if not path.exists():
            with httpx.Client(timeout=120, follow_redirects=True) as client:
                response = client.get(f"{base}/{relative}")
                response.raise_for_status()
                payload = response.content
            if name.endswith(".json"):
                json.loads(payload)
            elif not payload.startswith(b"diff --git"):
                raise ValueError("Not a candidate patch")
            path.write_bytes(payload)
        payload = path.read_bytes()
        record["artifacts"].append({"path": name, "sha256": digest(payload), "bytes": len(payload), "source": f"{base}/{relative}"})
    (case_dir / "preparation.json").write_text(json.dumps(record, indent=2) + "\n")
    return record


def materialize(record: dict, pull: bool) -> dict:
    case_dir = DEST / record["id"]
    repo = case_dir / "repository"
    image = record["image"]
    if pull:
        run("docker", "pull", image)
    inspected = json.loads(run("docker", "image", "inspect", image).stdout)[0]
    record["image_id"] = inspected["Id"]
    if repo.exists():
        record["repository_status"] = "existing_opaque_copy"
        return record
    name = run("docker", "create", "--network", "none", "--entrypoint", "sleep", image, "infinity").stdout.decode().strip()
    try:
        run("docker", "start", name)
        run("docker", "exec", name, "git", "config", "--global", "--add", "safe.directory", "/app")
        base = run("docker", "exec", name, "git", "-C", "/app", "rev-parse", "HEAD").stdout.decode().strip()
        if base != record["base_commit_hash"]:
            raise ValueError(f"Base mismatch: {base}")
        run("docker", "cp", str(case_dir / "model.patch"), name + ":/candidate.patch")
        run("docker", "exec", name, "git", "-C", "/app", "apply", "--whitespace=nowarn", "/candidate.patch")
        names = run("docker", "exec", name, "git", "-C", "/app", "ls-files", "--cached", "--others", "--exclude-standard", "-z").stdout
        archive = run("docker", "exec", "-i", name, "tar", "-C", "/app", "--null", "--ignore-failed-read", "-T", "-", "-cf", "-", input=names).stdout
        repo.mkdir()
        with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
            tar.extractall(repo, filter="data")
        record["repository_status"] = "base_plus_candidate_copied_without_source_inspection"
        record["repository_archive_sha256"] = digest(archive)
    finally:
        run("docker", "rm", "-f", name)
    return record


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--materialize", action="store_true")
    parser.add_argument("--pull", action="store_true")
    args = parser.parse_args()
    selected = json.loads(SELECTION.read_text())["selected"]
    DEST.mkdir(parents=True, exist_ok=True)
    with ThreadPoolExecutor(max_workers=3) as executor:
        records = list(executor.map(acquire, selected))
    if args.materialize:
        docker_root = json.loads(run("docker", "info", "--format", "{{json .DockerRootDir}}").stdout)
        if not docker_root.startswith("/data3/jhx/"):
            raise ValueError(f"Unexpected Docker storage: {docker_root}")
        for record in records:
            try:
                materialize(record, args.pull)
            except (subprocess.CalledProcessError, ValueError) as error:
                record["repository_status"] = "preparation_failed"
                record["preparation_error"] = str(error)
                if isinstance(error, subprocess.CalledProcessError):
                    record["preparation_stderr"] = error.stderr.decode(errors="replace")
            (DEST / record["id"] / "preparation.json").write_text(json.dumps(record, indent=2) + "\n")
            print(record["id"], record["repository_status"], flush=True)
    manifest = {"selection_sha256": digest(SELECTION.read_bytes()), "script_sha256": digest(Path(__file__).read_bytes()), "cases": records, "reference_or_verifier_read": False}
    (DEST / "preparation.json").write_text(json.dumps(manifest, indent=2) + "\n")
    registry = [{"id": row["id"], "task": row["id"], "language": row["language"],
                 "image": row["image"], "base_commit": row["base_commit_hash"],
                 "repository_name": row["repository"],
                 "repository": str(DEST / row["id"] / "repository"),
                 "candidate_patch": str(DEST / row["id"] / "model.patch"),
                 "issue": str(DEST / row["id"] / "issue.md"),
                 "trajectory": str(DEST / row["id"] / "trajectory.json")}
                for row in records]
    (DEST / "registry.json").write_text(json.dumps(registry, indent=2) + "\n")
    print(DEST / "preparation.json")


if __name__ == "__main__":
    main()
