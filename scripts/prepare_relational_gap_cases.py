"""Prepare source-only inputs and exact candidate environments for 17 trials.

The retrospective selection file supplies identifiers only. Verifiers, review
probes, reference patches, and manually selected validation steps are never
copied into generation inputs. Candidate repositories contain tracked base
files plus submitted patch additions, not arbitrary files from image /app.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import io
import json
from pathlib import Path
import re
import shutil
import subprocess
import tarfile
import tomllib

ROOT = Path(__file__).resolve().parents[1]
INPUTS = ROOT / "data/relational_gap_v1"
RESULTS = ROOT / "results/relational_gap_20260928"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(*args: str, **kwargs):
    return subprocess.run(args, check=True, capture_output=True, **kwargs)


def selected_cases() -> list[dict]:
    cases = []
    for row in json.loads((ROOT / "data/cases.json").read_text()):
        cases.append({**row, "source_dir": ROOT / "data/cases" / row["id"]})
    expanded = json.loads((ROOT / "research/expanded_trials_20260926/cases.json").read_text())
    for row in expanded["cases"]:
        source = ROOT / "results/expanded_trials_20260926/trials" / row["trial"]
        config = tomllib.loads((source / "task.toml").read_text())
        cases.append({"id": row["id"], "trial": row["trial"], "task": row["task"],
                      "base_commit": row["base_commit"],
                      "image": config["environment"]["docker_image"],
                      "source_dir": source})
    return cases


def language_for(row: dict) -> str:
    if row.get("language"):
        return row["language"]
    patch = (row["source_dir"] / "model.patch").read_text()
    paths = re.findall(r"^\+\+\+ b/(.+)$", patch, re.M)
    counts = {"python": 0, "go": 0, "typescript": 0}
    for path in paths:
        suffix = Path(path).suffix
        if suffix == ".py": counts["python"] += 1
        elif suffix == ".go": counts["go"] += 1
        elif suffix in {".ts", ".tsx", ".js"}: counts["typescript"] += 1
    return max(counts, key=counts.get)


def acquire(row: dict) -> dict:
    destination = INPUTS / row["id"]
    destination.mkdir(parents=True, exist_ok=True)
    source = row["source_dir"]
    allowed = {"issue.md": "issue.md" if (source / "issue.md").exists() else "instruction.md",
               "model.patch": "model.patch", "trajectory.json": "trajectory.json"}
    artifacts = []
    for target, original in allowed.items():
        shutil.copy2(source / original, destination / target)
        artifacts.append({"path": target, "sha256": digest(destination / target),
                          "source": str((source / original).relative_to(ROOT))})
    record = {key: row[key] for key in ("id", "trial", "task", "image", "base_commit")}
    record.update(language=language_for(row), repository=str(destination / "repository"),
                  candidate_patch=str(destination / "model.patch"), issue=str(destination / "issue.md"),
                  trajectory=str(destination / "trajectory.json"), artifacts=artifacts,
                  source_roles=["issue", "submitted_candidate", "existing_validation_trajectory"],
                  excluded_roles=["verifier", "reference", "manual_probe", "case_label"])
    return record


def materialize(record: dict, pull_missing: bool) -> dict:
    image = record["image"]
    inspected = subprocess.run(["docker", "image", "inspect", image], capture_output=True)
    if inspected.returncode and pull_missing:
        log = RESULTS / "preparation" / (record["id"] + ".pull.log")
        log.parent.mkdir(parents=True, exist_ok=True)
        with log.open("w") as handle:
            subprocess.run(["docker", "pull", image], stdout=handle, stderr=subprocess.STDOUT,
                           check=True, timeout=3600)
        inspected = run("docker", "image", "inspect", image)
    if inspected.returncode:
        record.update(environment_status="missing_image", repository_status="not_prepared")
        return record
    record["image_id"] = json.loads(inspected.stdout)[0]["Id"]
    repository = Path(record["repository"])
    stamp = repository.parent / "repository_provenance.json"
    if stamp.exists() and repository.exists():
        previous = json.loads(stamp.read_text())
        if previous.get("image_id") == record["image_id"] and previous.get("patch_sha256") == digest(Path(record["candidate_patch"])):
            record.update(environment_status="image_available", repository_status="prepared", repository_provenance=previous)
            return record
        raise ValueError("Existing repository provenance differs; refusing to replace it")
    name = run("docker", "create", "--network", "none", "--entrypoint", "sleep", image, "infinity").stdout.decode().strip()
    try:
        run("docker", "start", name)
        run("docker", "exec", name, "git", "config", "--global", "--add", "safe.directory", "/app")
        head = run("docker", "exec", name, "git", "-C", "/app", "rev-parse", "HEAD").stdout.decode().strip()
        if head != record["base_commit"]:
            raise ValueError(f"Base mismatch: expected {record['base_commit']}, found {head}")
        run("docker", "cp", record["candidate_patch"], name + ":/candidate.patch")
        run("docker", "exec", name, "git", "-C", "/app", "apply", "--whitespace=nowarn", "/candidate.patch")
        names = set(run("docker", "exec", name, "git", "-C", "/app", "ls-files", "--cached", "-z").stdout.split(b"\0"))
        patch = Path(record["candidate_patch"]).read_text()
        names.update(path.encode() for path in re.findall(r"^\+\+\+ b/(.+)$", patch, re.M))
        names.discard(b"")
        archive = run("docker", "exec", "-i", name, "tar", "-C", "/app", "--null", "--ignore-failed-read", "-T", "-", "-cf", "-", input=b"\0".join(sorted(names)) + b"\0").stdout
        repository.mkdir(exist_ok=True)
        with tarfile.open(fileobj=io.BytesIO(archive)) as bundle:
            bundle.extractall(repository, filter="data")
        provenance = {"image_id": record["image_id"], "base_commit": head,
                      "patch_sha256": digest(Path(record["candidate_patch"])),
                      "archive_sha256": hashlib.sha256(archive).hexdigest(),
                      "selection": "tracked base files plus submitted patch paths", "files": len(names)}
        stamp.write_text(json.dumps(provenance, indent=2) + "\n")
        record.update(environment_status="image_available", repository_status="prepared", repository_provenance=provenance)
    finally:
        run("docker", "rm", "-f", name)
    return record


def write_registry(records: list[dict]) -> None:
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "case_registry.json").write_text(json.dumps(records, indent=2) + "\n")
    # Exactly the same allowlisted metadata is exposed to generation; no labels.
    (INPUTS / "registry.json").write_text(json.dumps(records, indent=2) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--materialize", action="store_true")
    parser.add_argument("--pull-missing", action="store_true")
    parser.add_argument("--cases", nargs="*")
    parser.add_argument("--workers", type=int, default=3)
    args = parser.parse_args()
    rows = selected_cases()
    records = [acquire(row) for row in rows]
    if args.materialize:
        docker_root = run("docker", "info", "--format", "{{.DockerRootDir}}").stdout.decode().strip()
        if docker_root != "/data3/jhx" and not docker_root.startswith("/data3/jhx/"):
            raise ValueError(f"Unexpected Docker storage: {docker_root}")
        def prepare(record):
            try:
                if args.cases and record["id"] not in args.cases:
                    stamp = Path(record["repository"]).parent / "repository_provenance.json"
                    if stamp.exists():
                        record.update(repository_status="prepared", repository_provenance=json.loads(stamp.read_text()))
                    return record
                return materialize(record, args.pull_missing)
            except Exception as error:
                record.update(environment_status="preparation_error", error=str(error))
                if isinstance(error, subprocess.CalledProcessError):
                    record["stderr"] = (error.stderr or b"").decode(errors="replace")
                return record
        with ThreadPoolExecutor(max_workers=args.workers) as executor:
            pending = {executor.submit(prepare, record): record["id"] for record in records}
            completed = {}
            for future in as_completed(pending):
                result = future.result()
                completed[result["id"]] = result
                print(result["id"], result.get("environment_status"), result.get("repository_status"), flush=True)
                write_registry([completed.get(r["id"], r) for r in records])
            records = [completed[r["id"]] for r in records]
    write_registry(records)
    print(RESULTS / "case_registry.json")


if __name__ == "__main__":
    main()
