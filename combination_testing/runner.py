"""Execute frozen generated tests locally; reference patches are evaluator-only inputs.

Generation never imports the reference resolver. A paired run is a differential
check, not by itself proof that its oracle is valid or that all bugs were found.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import uuid
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
FORMATS = {"pytest-junit", "go-json", "vitest-json", "jsonl"}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def safe_relative(value: str) -> str:
    path = PurePosixPath(value)
    if not value or path.is_absolute() or ".." in path.parts or value in {".", ""}:
        raise ValueError(f"Expected repository-relative path: {value!r}")
    return str(path)


def freeze_artifact(directory: Path, case_id: str, files: dict[str, str], command: str,
                    report_format: str, report_path: str, *, timeout: int = 180,
                    metadata: dict | None = None) -> dict:
    """Freeze repo-relative UTF-8 source strings and their execution command."""
    if report_format not in FORMATS:
        raise ValueError(f"Unknown test report format: {report_format}")
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=False)
    entries = []
    for target, content in sorted(files.items()):
        target = safe_relative(target)
        source = directory / "files" / target
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text(content)
        entries.append({"source": str(source.relative_to(directory)), "target": target,
                        "sha256": sha256(source)})
    manifest = {"case_id": case_id, "files": entries, "command": command,
                "timeout": timeout,
                "report": {"format": report_format, "path": safe_relative(report_path)},
                "metadata": metadata or {}}
    (directory / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


def load_artifact(directory: Path) -> dict:
    directory = Path(directory).resolve()
    manifest = json.loads((directory / "manifest.json").read_text())
    if manifest["report"]["format"] not in FORMATS:
        raise ValueError("Unknown report format")
    safe_relative(manifest["report"]["path"])
    targets = set()
    for item in manifest["files"]:
        source = directory / safe_relative(item["source"])
        if not source.resolve().is_relative_to(directory):
            raise ValueError("Artifact source escapes the frozen artifact directory")
        target = safe_relative(item["target"])
        if target in targets:
            raise ValueError(f"Duplicate artifact target: {target}")
        targets.add(target)
        if sha256(source) != item["sha256"]:
            raise ValueError(f"Frozen artifact changed: {source}")
    return manifest


def reference_patch_for(case: dict) -> Path:
    """Evaluator-only path resolution; never supplies patch content to generation."""
    directory = Path(os.environ.get("COMBINATION_REFERENCE_ROOT",
                     "/home/jhx/oracle_gap/data/cache/pilot-tasks-instrumented"))
    path = directory / case["task"] / "solution" / "solution.patch"
    if not path.is_file():
        raise FileNotFoundError(f"Independent reference patch unavailable: {path}")
    return path


def run_artifact(directory: Path, program: str, output: Path, *,
                 reference_patch: Path | None = None,
                 registry: Path | list[dict] | dict | None = None,
                 case_root: Path | None = None) -> dict:
    """Run exactly one frozen artifact in a fresh network-isolated container."""
    from combination_testing.test_reports import parse_report

    directory, output = Path(directory).resolve(), Path(output).resolve()
    manifest = load_artifact(directory)
    registry_rows = json.loads((ROOT / "data/cases.json").read_text()) if registry is None else (
        json.loads(Path(registry).read_text()) if isinstance(registry, (str, Path)) else registry)
    if isinstance(registry_rows, dict):
        registry_rows = registry_rows["cases"]
    case = dict(next(c for c in registry_rows if c["id"] == manifest["case_id"]))
    if "base_commit" not in case:
        case["base_commit"] = case["base_commit_hash"]
    case.setdefault("task", case["id"])
    case_root = Path(case_root) if case_root is not None else ROOT / "data/cases"
    if program not in {"candidate", "reference", "base"}:
        raise ValueError(f"Unknown program: {program}")
    patch = None
    if program == "candidate":
        if case.get("candidate_patch"):
            patch = Path(case["candidate_patch"])
            if not patch.is_absolute():
                patch = case_root / patch
        else:
            patch = case_root / case["id"] / "model.patch"
    elif program == "reference":
        patch = Path(reference_patch) if reference_patch else reference_patch_for(case)
    output.mkdir(parents=True, exist_ok=False)
    # Snapshot input bytes; execution never relies on mutable generation outputs.
    frozen = output / "artifact"
    shutil.copytree(directory, frozen)
    load_artifact(frozen)
    patch_copy = None
    if patch:
        patch_copy = output / "implementation.patch"
        shutil.copyfile(patch, patch_copy)
    image = subprocess.run(["docker", "image", "inspect", "--format", "{{.Id}}", case["image"]],
                           capture_output=True, text=True, check=True).stdout.strip()
    request = {"program": program, "manifest": manifest, "base_commit": case["base_commit"],
               "uid": os.getuid(), "gid": os.getgid()}
    (output / "request.json").write_text(json.dumps(request, indent=2) + "\n")
    name = "combination-" + uuid.uuid4().hex[:16]
    command = ["docker", "run", "--rm", "--name", name, "--interactive", "--init",
               "--network", "none", "--cpus", "2", "--memory", "8g",
               "--mount", f"type=bind,src={ROOT / 'combination_testing/container_runner.py'},dst=/combination-runner.py,readonly",
               "--mount", f"type=bind,src={frozen},dst=/artifact,readonly",
               "--mount", f"type=bind,src={output},dst=/combination-logs"]
    if patch_copy:
        command += ["--mount", f"type=bind,src={patch_copy},dst=/implementation.patch,readonly"]
    command += ["--entrypoint", "python3", image, "/combination-runner.py"]
    transport = {"returncode": None}
    try:
        proc = subprocess.run(command, input=json.dumps(request), capture_output=True,
                              text=True, timeout=int(manifest.get("timeout", 180)) + 120)
        transport = {"returncode": proc.returncode}
        (output / "transport.stdout").write_text(proc.stdout)
        (output / "transport.stderr").write_text(proc.stderr)
    except subprocess.TimeoutExpired as exc:
        transport = {"returncode": None, "error": "docker transport timeout"}
        for name_, value in (("stdout", exc.stdout), ("stderr", exc.stderr)):
            (output / f"transport.{name_}").write_bytes(value if isinstance(value, bytes) else (value or "").encode())
    finally:
        subprocess.run(["docker", "rm", "--force", name], capture_output=True, check=False)
    process_path = output / "process.json"
    process = json.loads(process_path.read_text()) if process_path.exists() else {
        "stage": "transport", "error": "container did not produce process.json"}
    tests = parse_report(output, manifest["report"], process)
    result = {"case_id": case["id"], "program": program,
              "artifact_sha256": sha256(frozen / "manifest.json"),
              "patch_sha256": sha256(patch_copy) if patch_copy else None,
              "image_id": image, "base_commit": case["base_commit"],
              "created_at": datetime.now(timezone.utc).isoformat(),
              "transport": transport, "process": process, **tests}
    (output / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    return result


def compare_pair(candidate: dict, reference: dict) -> dict:
    """Keep invalid tests and harness failures out of defect witness counts."""
    if candidate["artifact_sha256"] != reference["artifact_sha256"]:
        raise ValueError("Cannot compare different frozen artifacts")
    ctests = {t["id"]: t for t in candidate["tests"]}
    rtests = {t["id"]: t for t in reference["tests"]}
    rows = []
    for test_id in sorted(ctests.keys() | rtests.keys()):
        c, r = ctests.get(test_id), rtests.get(test_id)
        if candidate.get("errors") or reference.get("errors"):
            classification = "execution_error"
        elif c is None or r is None:
            classification = "missing_test_result"
        elif any(t["status"] == "error" and t.get("kind") == "invalid_input_or_oracle" for t in (c, r)):
            classification = "oracle_precondition_rejected"
        elif c["status"] == "error" or r["status"] == "error":
            classification = "execution_error"
        elif r["status"] == "fail":
            classification = "reference_rejected_test"
        elif c["status"] == "fail" and r["status"] == "pass":
            classification = "differential_witness"
        elif c["status"] == r["status"] == "pass":
            classification = "no_difference"
        else:
            classification = "inconclusive"
        rows.append({"id": test_id, "candidate": c["status"] if c else None,
                     "reference": r["status"] if r else None,
                     "classification": classification})
    counts = {name: sum(row["classification"] == name for row in rows) for name in
              ("differential_witness", "no_difference", "reference_rejected_test",
               "execution_error", "oracle_precondition_rejected", "missing_test_result", "inconclusive")}
    return {"case_id": candidate["case_id"], "artifact_sha256": candidate["artifact_sha256"],
            "candidate_run_status": candidate["status"], "reference_run_status": reference["status"],
            "counts": counts, "tests": rows,
            "interpretation": "A differential witness requires an independently justified input and oracle; reference acceptance alone is not a proof of validity."}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("artifact", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--program", choices=("candidate", "reference", "base", "pair"), default="pair")
    parser.add_argument("--reference-patch", type=Path)
    args = parser.parse_args()
    if args.program == "pair":
        candidate = run_artifact(args.artifact, "candidate", args.output / "candidate")
        reference = run_artifact(args.artifact, "reference", args.output / "reference",
                                 reference_patch=args.reference_patch)
        result = compare_pair(candidate, reference)
        (args.output / "comparison.json").write_text(json.dumps(result, indent=2) + "\n")
    else:
        result = run_artifact(args.artifact, args.program, args.output, reference_patch=args.reference_patch)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
