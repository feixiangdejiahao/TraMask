"""Compile each Go package once, then run selected tests in fresh processes.

The timeout is one deadline for package discovery, compilation, and every test.
Before each test, its allowance is the remaining time divided by the remaining
test count. A stuck test therefore cannot consume the other tests' shares.

``--tests`` accepts a JSON list (applied to each supplied package), or a mapping
from package arguments to lists. Prefix a JSON filename with ``@`` or supply an
existing filename directly. Names are exact runtime test names, not regexes.
The ordinary Go event stream is written to ``--report``. Detailed compile and
timeout outcomes live beside it in ``<report-stem>.runner.json`` and
``<report-stem>.runner/``. Timeouts never become synthetic testcase failures.

This standalone helper needs only Python's standard library and the local Go
toolchain. It is deliberately independent of corpus IDs and generation code.
"""
from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import re
import signal
import subprocess
import time


TERMINAL = {"pass", "fail", "skip"}


def _write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2) + "\n")


def _selection(packages: list[str], tests: list[str] | dict[str, list[str]]) -> dict[str, list[str]]:
    packages = list(dict.fromkeys(packages))
    if not packages or any(not isinstance(p, str) or not p or "..." in p for p in packages):
        raise ValueError("Supply concrete package names, not package wildcards")
    if isinstance(tests, list):
        tests = {package: tests for package in packages}
    if not isinstance(tests, dict) or set(tests) != set(packages):
        raise ValueError("Test mapping must contain exactly the supplied packages")
    selected = {}
    for package in packages:
        names = tests[package]
        if (not isinstance(names, list) or not names
                or any(not isinstance(name, str) or not name
                       or any(char in name for char in "\n\r\0")
                       or any(not part for part in name.split("/")) for name in names)):
            raise ValueError("Each package requires nonempty exact test names")
        selected[package] = list(dict.fromkeys(names))
    return selected


def exact_pattern(name: str) -> str:
    """Go splits -test.run at slashes; anchor and escape every component."""
    return "/".join("^" + re.escape(part) + "$" for part in name.split("/"))


def _command(command: list[str], cwd: Path, directory: Path, allowance: float) -> dict:
    directory.mkdir(parents=True, exist_ok=False)
    stdout_path, stderr_path = directory / "stdout.txt", directory / "stderr.txt"
    started = time.monotonic()
    result = {"command": command, "cwd": str(cwd), "allowance_seconds": allowance,
              "stdout": str(stdout_path), "stderr": str(stderr_path),
              "returncode": None, "timed_out": False}
    with stdout_path.open("w") as stdout, stderr_path.open("w") as stderr:
        if allowance <= 0:
            result["error"] = "budget_exhausted"
        else:
            try:
                process = subprocess.Popen(command, cwd=cwd, stdout=stdout, stderr=stderr,
                                           start_new_session=True)
                try:
                    process.wait(timeout=max(0, allowance - (time.monotonic() - started)))
                except subprocess.TimeoutExpired:
                    result["timed_out"] = True
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    process.wait()
                result["returncode"] = process.returncode
            except OSError as exc:
                result["error"] = f"{type(exc).__name__}: {exc}"
    result["elapsed_seconds"] = time.monotonic() - started
    _write_json(directory / "process.json", result)
    return result


def _events(path: Path) -> tuple[list[dict], list[str]]:
    events, errors = [], []
    for number, line in enumerate(path.read_text(errors="replace").splitlines(), 1):
        try:
            event = json.loads(line)
            if not isinstance(event, dict) or not isinstance(event.get("Action"), str):
                raise ValueError("missing Go event action")
            events.append(event)
        except ValueError as exc:
            errors.append(f"line {number}: {exc}")
    return events, errors


def run(packages: list[str], tests: list[str] | dict[str, list[str]], *,
        timeout: float, report: Path, repository: Path | None = None,
        go: str = "go") -> dict:
    """Return an auditable summary; exit_code distinguishes tests from errors."""
    selected = _selection(packages, tests)
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("timeout must be a finite positive number of seconds")
    repository = (repository or Path.cwd()).resolve()
    report = Path(report).resolve()
    report.parent.mkdir(parents=True, exist_ok=True)
    details = report.with_name(report.stem + ".runner")
    summary_path = report.with_name(report.stem + ".runner.json")
    if report.exists() or summary_path.exists():
        raise FileExistsError("Refusing to replace an existing test report")
    details.mkdir(exist_ok=False)
    started = time.monotonic()
    deadline = started + timeout
    summary = {"repository": str(repository), "timeout_seconds": timeout,
               "budget_includes": ["package_discovery", "compilation", "test_processes"],
               "allocation": "remaining_seconds / remaining_test_count",
               "report": str(report), "summary": str(summary_path),
               "packages": [], "tests": []}
    jobs = []
    # Compile first so every successfully built package participates in the
    # same fair test-process budget. All commands use the same deadline.
    for index, (package, names) in enumerate(selected.items()):
        package_dir = details / f"package_{index:03}"
        package_dir.mkdir()
        item = {"package": package, "selected_tests": names}
        summary["packages"].append(item)
        listing = _command([go, "list", "-json", package], repository,
                           package_dir / "discovery", deadline - time.monotonic())
        item["discovery"] = listing
        if listing["returncode"] != 0 or listing["timed_out"] or listing.get("error"):
            item["status"] = "discovery_timeout" if listing["timed_out"] else "discovery_error"
        else:
            try:
                metadata = json.loads(Path(listing["stdout"]).read_text())
                package_cwd = Path(metadata["Dir"])
                import_path = metadata["ImportPath"]
                if not package_cwd.is_absolute() or not isinstance(import_path, str) or not import_path:
                    raise ValueError("invalid Go package metadata")
            except (ValueError, KeyError, TypeError) as exc:
                item.update(status="discovery_error", error=str(exc))
            else:
                item.update(import_path=import_path, directory=str(package_cwd))
                binary = package_dir / "package.test"
                compilation = _command([go, "test", "-c", "-o", str(binary), package],
                                       repository, package_dir / "compilation",
                                       deadline - time.monotonic())
                item["compilation"] = compilation
                build_output = package_dir / "build-output.txt"
                build_output.write_text(Path(compilation["stdout"]).read_text(errors="replace")
                                        + Path(compilation["stderr"]).read_text(errors="replace"))
                item["build_output"] = str(build_output)
                if compilation["timed_out"]:
                    item["status"] = "compile_timeout"
                elif compilation["returncode"] != 0 or compilation.get("error") or not binary.is_file():
                    item["status"] = "compile_error"
                else:
                    item["status"] = "compiled"
                    jobs.extend((item, name, binary, package_cwd) for name in names)
        if item["status"] != "compiled":
            summary["tests"].extend({"package": package, "test": name, "status": "not_run",
                                     "reason": item["status"]} for name in names)
    with report.open("w") as destination:
        for index, (package, name, binary, cwd) in enumerate(jobs):
            allowance = max(0.0, (deadline - time.monotonic()) / (len(jobs) - index))
            command = [go, "tool", "test2json", "-t", "-p", package["import_path"],
                       str(binary), "-test.v", "-test.paniconexit0", "-test.count=1",
                       "-test.timeout=0", "-test.run=" + exact_pattern(name)]
            process = _command(command, cwd, details / f"test_{index:04}", allowance)
            events, errors = _events(Path(process["stdout"]))
            row = {"package": package["package"], "import_path": package["import_path"],
                   "test": name, "process": process}
            if process["timed_out"]:
                row["status"] = "timeout"
                # Keep the exact raw stream in process.stdout, but do not let
                # partial terminal events classify a timed-out invocation as
                # either a semantic failure or a completed passing test.
                published = [event for event in events if event["Action"] not in TERMINAL]
            else:
                published = events
                terminal = [event for event in events
                            if event.get("Test") == name and event["Action"] in TERMINAL]
                if process.get("error"):
                    row.update(status="not_run" if process["error"] == "budget_exhausted" else "error",
                               reason=process["error"])
                elif errors:
                    row.update(status="report_error", errors=errors)
                elif not terminal:
                    row.update(status="missing_outcome", reason="No terminal event for the exact selected test")
                else:
                    row["status"] = terminal[-1]["Action"]
                    if process["returncode"] != 0 and row["status"] != "fail":
                        row.update(status="error", reason="Nonzero process exit after a non-failing test")
            for event in published:
                destination.write(json.dumps(event) + "\n")
            destination.flush()
            summary["tests"].append(row)
    statuses = [row["status"] for row in summary["tests"]]
    infrastructure_error = any(status not in TERMINAL for status in statuses)
    exit_code = 2 if infrastructure_error else 1 if "fail" in statuses else 0
    summary.update(exit_code=exit_code,
                   status="error" if infrastructure_error else "fail" if "fail" in statuses else "pass",
                   counts={status: statuses.count(status) for status in sorted(set(statuses))},
                   elapsed_seconds=time.monotonic() - started)
    _write_json(summary_path, summary)
    return summary


def _read_tests(value: str) -> list[str] | dict[str, list[str]]:
    if value.startswith("@"):
        return json.loads(Path(value[1:]).read_text())
    if not value.lstrip().startswith(("[", "{")):
        return json.loads(Path(value).read_text())
    return json.loads(value)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", action="append", required=True,
                        help="Concrete Go package; repeat for several packages")
    parser.add_argument("--tests", required=True, help="Exact names as JSON, JSON file, or @JSON file")
    parser.add_argument("--timeout", type=float, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--repository", type=Path, default=Path.cwd())
    parser.add_argument("--go", default="go")
    args = parser.parse_args(argv)
    result = run(args.package, _read_tests(args.tests), timeout=args.timeout,
                 report=args.report, repository=args.repository, go=args.go)
    print(json.dumps({key: result[key] for key in ("status", "counts", "elapsed_seconds", "summary")}))
    return result["exit_code"]


if __name__ == "__main__":
    raise SystemExit(main())
