"""Freeze and execute test-file edits using explicit environment metadata.

This module never creates combinations or derives oracles. Reference inputs are
explicit evaluator arguments; local fixtures run from disposable copies.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import signal
import subprocess
import time

from combination_testing import runner as existing
from combination_testing.test_reports import parse_report

NODE_REPORTER = '''export default async function* (events) {
  for await (const event of events) {
    if (event.type !== 'test:pass' && event.type !== 'test:fail') continue;
    const data = event.data;
    if (data.details?.type === 'suite') continue;
    yield 'CC_RESULT ' + JSON.stringify({id: data.name,
      status: data.skip || data.todo ? 'skip' : event.type === 'test:pass' ? 'pass' : 'fail',
      detail: String(data.details?.error?.stack ?? '')}) + '\\n';
  }
}
'''


def registry_cases(registry: Path | list[dict] | dict) -> list[dict]:
    value = json.loads(Path(registry).read_text()) if isinstance(registry, (str, Path)) else registry
    return value["cases"] if isinstance(value, dict) else value


def infer_harness(repository: Path, language: str, targets: list[str], *,
                  python: str = "python", name_filter: str | None = None) -> dict:
    """Infer standard test-framework invocation; no repository/task-name rules."""
    repository = Path(repository).resolve()
    targets = sorted({existing.safe_relative(x) for x in targets})
    quoted = " ".join(shlex.quote(x) for x in targets)
    if not targets:
        raise ValueError("No test files supplied")
    if language == "python":
        selector = " -k " + shlex.quote(name_filter) if name_filter else ""
        return {"command": f'{shlex.quote(python)} -m pytest -q {quoted}{selector} --junitxml="$COMBINATION_REPORT_DIR/junit.xml"',
                "report_format": "pytest-junit", "report_path": "junit.xml", "files": {}}
    if language == "go":
        packages = sorted({"./" if Path(x).parent == Path(".") else "./" + str(Path(x).parent) for x in targets})
        selector = " -run " + shlex.quote(name_filter) if name_filter else ""
        return {"command": 'go test -count=1 -json' + selector + " " + " ".join(shlex.quote(x) for x in packages) + ' > "$COMBINATION_REPORT_DIR/go.jsonl"',
                "report_format": "go-json", "report_path": "go.jsonl", "files": {}}
    if language not in {"typescript", "javascript"}:
        raise ValueError(f"Unsupported harness language: {language}")
    package_roots = set()
    for target in targets:
        parent = (repository / target).parent
        while parent != repository and not (parent / "package.json").exists():
            parent = parent.parent
        package_roots.add(parent)
    if len(package_roots) != 1:
        raise ValueError("Separate artifacts are required for separate JS packages")
    package_root = package_roots.pop()
    package_path = package_root / "package.json"
    package = json.loads(package_path.read_text()) if package_path.exists() else {}
    dependencies = {**package.get("dependencies", {}), **package.get("devDependencies", {})}
    relative_targets = [str((repository / x).relative_to(package_root)) for x in targets]
    quoted = " ".join(shlex.quote(x) for x in relative_targets)
    prefix = "" if package_root == repository else "cd " + shlex.quote(str(package_root.relative_to(repository))) + " && "
    parents = [package_root, *package_root.parents]
    pnpm = any((p / "pnpm-lock.yaml").exists() for p in parents if p == repository or repository in p.parents)
    manager = "pnpm exec " if pnpm else "npx --no-install "
    selector = " -t " + shlex.quote(name_filter) if name_filter else ""
    if "vitest" in dependencies:
        return {"command": prefix + manager + 'vitest run ' + quoted + selector + ' --reporter=json --outputFile="$COMBINATION_REPORT_DIR/vitest.json"',
                "report_format": "vitest-json", "report_path": "vitest.json", "files": {}}
    if "jest" in dependencies:
        return {"command": prefix + manager + 'jest --runInBand ' + quoted + selector + ' --json --outputFile="$COMBINATION_REPORT_DIR/jest.json"',
                "report_format": "vitest-json", "report_path": "jest.json", "files": {}}
    sources = "\n".join((repository / x).read_text() for x in targets if (repository / x).exists())
    if "node:test" in sources or "node --test" in package.get("scripts", {}).get("test", ""):
        reporter = str(package_root.relative_to(repository) / ".generic-node-reporter.mjs")
        selector = " --test-name-pattern=" + shlex.quote(name_filter) if name_filter else ""
        return {"command": prefix + 'node --test --test-isolation=none --test-reporter=./.generic-node-reporter.mjs' + selector + " " + quoted,
                "report_format": "jsonl", "report_path": "stdout.txt", "files": {reporter: NODE_REPORTER}}
    raise ValueError("No supported test framework declared; supply an explicit harness")


def freeze_artifact(directory: Path, case_id: str, files: dict[str, str], command: str,
                    report_format: str, report_path: str, *, repository: Path,
                    obligations: list[dict], timeout: int = 180,
                    metadata: dict | None = None) -> dict:
    """Freeze whole edited test files plus exact source/control provenance."""
    repository = Path(repository).resolve()
    relations = []
    identifiers = set()
    for row in obligations:
        row = dict(row)
        if not row.get("id") or row["id"] in identifiers:
            raise ValueError("Every obligation needs a unique ID")
        identifiers.add(row["id"])
        controls = row.pop("control_ids", row.get("controls", []))
        if isinstance(controls, str):
            controls = [controls]
        controls = [*controls, *[row[key] for key in ("control", "control_id") if row.get(key)]]
        if not row.get("is_control") and not controls:
            raise ValueError("Generated tests must declare their source controls")
        row["controls"] = list(dict.fromkeys(controls))
        relations.append(row)
    source_files = []
    for target in sorted(files):
        source = repository / existing.safe_relative(target)
        if not source.resolve().is_relative_to(repository):
            raise ValueError("Original test path escapes repository")
        source_files.append({"path": target, "sha256": existing.sha256(source) if source.is_file() else None})
    meta = {**(metadata or {}), "obligations": relations,
            "controls": sorted({x for row in relations for x in row["controls"]}),
            "source_files": source_files, "source_repository": str(repository)}
    return existing.freeze_artifact(directory, case_id, files, command, report_format,
                                    report_path, timeout=timeout, metadata=meta)


def _tree_digest(directory: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(directory.rglob("*")):
        if path.is_file() and not path.is_symlink() and ".git" not in path.relative_to(directory).parts:
            digest.update(str(path.relative_to(directory)).encode() + b"\0")
            digest.update(path.read_bytes())
    return digest.hexdigest()


def _normalize_go_subtests(result: dict, manifest: dict) -> dict:
    """Expose declared Go parent tests to the existing parameterized-ID matcher."""
    if manifest["report"]["format"] != "go-json":
        return result
    declared = set(manifest.get("metadata", {}).get("controls", []))
    for row in manifest.get("metadata", {}).get("obligations", []):
        declared.add(row.get("test_name") or row["id"])
        declared.update(row.get("controls", []))
    for row in result["tests"]:
        prefix, separator, local = row["id"].partition("::")
        matches = [name for name in declared if local.startswith(name + "/")]
        if separator and len(matches) == 1:
            name = matches[0]
            row["raw_id"] = row["id"]
            row["id"] = prefix + "::" + name + "[" + local[len(name) + 1:] + "]"
    return result


def run_artifact(directory: Path, program: str, output: Path, *,
                 registry: Path | list[dict] | dict,
                 case_root: Path | None = None,
                 reference_patch: Path | None = None,
                 reference_repository: Path | None = None) -> dict:
    manifest = existing.load_artifact(directory)
    cases = registry_cases(registry)
    case = next(row for row in cases if row["id"] == manifest["case_id"])
    if case.get("image"):
        result = existing.run_artifact(directory, program, output, registry=cases,
                                       case_root=case_root, reference_patch=reference_patch)
        _normalize_go_subtests(result, manifest)
        (Path(output) / "result.json").write_text(json.dumps(result, indent=2) + "\n")
        return result
    if program not in {"candidate", "reference", "base"}:
        raise ValueError(f"Unknown program: {program}")
    if program == "reference":
        if reference_repository is None:
            raise ValueError("Local reference execution requires an explicit reference_repository")
        source = Path(reference_repository)
    elif program == "base":
        if not case.get("base_repository"):
            raise ValueError("Local base execution requires an explicit base_repository")
        source = Path(case["base_repository"])
    else:
        source = Path(case["repository"])
    if not source.is_absolute() and case_root is not None:
        source = Path(case_root) / source
    source = source.resolve()
    if not source.is_dir():
        raise FileNotFoundError(source)
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    frozen = output / "artifact"
    shutil.copytree(Path(directory).resolve(), frozen)
    existing.load_artifact(frozen)
    workspace = output / "workspace"
    shutil.copytree(source, workspace, symlinks=True,
                    ignore=shutil.ignore_patterns(".git", "__pycache__", ".pytest_cache"))
    implementation_hash = _tree_digest(workspace)
    process = {"stage": "artifact_copy", "returncode": None}
    started = time.monotonic()
    try:
        for entry in manifest["files"]:
            target = workspace / entry["target"]
            if not target.resolve().is_relative_to(workspace):
                raise ValueError("Test target escapes local workspace")
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(frozen / entry["source"], target)
        environment = {**os.environ, "COMBINATION_REPORT_DIR": str(output),
                       "PIP_NO_INDEX": "1", "GOPROXY": "off", "GOTOOLCHAIN": "local"}
        process["stage"] = "test"
        with (output / "stdout.txt").open("w") as stdout, (output / "stderr.txt").open("w") as stderr:
            child = subprocess.Popen(["bash", "-lc", manifest["command"]], cwd=workspace,
                                     stdout=stdout, stderr=stderr, env=environment,
                                     start_new_session=True)
            try:
                process["returncode"] = child.wait(timeout=int(manifest.get("timeout", 180)))
                process["stage"] = "finished"
            except subprocess.TimeoutExpired:
                os.killpg(child.pid, signal.SIGKILL)
                child.wait()
                process.update(stage="timeout", error="Test command exceeded timeout", timed_out=True)
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        process["error"] = str(exc)
    process["elapsed_seconds"] = time.monotonic() - started
    (output / "process.json").write_text(json.dumps(process, indent=2) + "\n")
    result = {"case_id": case["id"], "program": program,
              "artifact_sha256": existing.sha256(frozen / "manifest.json"),
              "implementation_sha256": implementation_hash,
              "created_at": datetime.now(timezone.utc).isoformat(),
              "backend": "local_disposable_copy", "network_isolation": False,
              "transport": {"returncode": process["returncode"]}, "process": process,
              **parse_report(output, manifest["report"], process)}
    _normalize_go_subtests(result, manifest)
    (output / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    return result


def run_pair(directory: Path, output: Path, **kwargs) -> dict:
    candidate = run_artifact(directory, "candidate", Path(output) / "candidate", **kwargs)
    reference = run_artifact(directory, "reference", Path(output) / "reference", **kwargs)
    comparison = existing.compare_pair(candidate, reference)
    (Path(output) / "comparison.json").write_text(json.dumps(comparison, indent=2) + "\n")
    from combination_testing.evaluate import evaluate_case
    evaluation = evaluate_case(Path(directory), Path(output))
    (Path(output) / "evaluation.json").write_text(json.dumps(evaluation, indent=2) + "\n")
    return evaluation


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("artifact", type=Path)
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument("--case-root", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--program", choices=("candidate", "reference", "base", "pair"), default="candidate")
    parser.add_argument("--reference-patch", type=Path)
    parser.add_argument("--reference-repository", type=Path)
    args = parser.parse_args()
    kwargs = {key: getattr(args, key) for key in ("registry", "case_root", "reference_patch", "reference_repository")}
    result = run_pair(args.artifact, args.output, **kwargs) if args.program == "pair" else run_artifact(args.artifact, args.program, args.output, **kwargs)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
