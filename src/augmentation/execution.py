"""Execute caller-selected test commands in a copy of the completed repository."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import shutil
import signal
import subprocess
import time

from .pipeline import parse_response, write_json


def _copy_repository(source, destination):
    def ignore(directory, names):
        return [n for n in names if n in {".git", ".venv", ".pytest_cache", "__pycache__", ".env", ".aws", ".codex", ".agents"}
                or n.startswith(".env.") or ((Path(directory) / n).is_symlink()
                    and not (Path(directory) / n).resolve().is_relative_to(source))]
    shutil.copytree(source, destination, ignore=ignore, symlinks=True)
    # Resolve links against the original tree, before rewriting any targets.
    # Even a relative link can leave the copy if it walks out and back by name.
    for directory, dirs, files in os.walk(destination, followlinks=False):
        for name in dirs + files:
            link = Path(directory) / name
            if link.is_symlink():
                original = source / link.relative_to(destination)
                relative = original.resolve().relative_to(source)
                link.unlink()
                link.symlink_to(os.path.relpath(destination / relative, link.parent))


def _command(command, paths):
    if not isinstance(command, list) or not command or any(not isinstance(x, str) or not x for x in command):
        raise ValueError("command_must_be_an_argv_array")
    expanded = []
    for arg in command:
        if arg == "{test_paths}":
            expanded.extend(sorted(set(paths)))
        else:
            expanded.append(arg)
    return expanded


def _run(command, cwd, directory, timeout, candidate=None):
    directory.mkdir()
    started = time.monotonic()
    env, setup = None, None
    if candidate is not None:
        from .feedback import probe_environment
        env, setup = probe_environment(candidate, cwd, directory)
    try:
        with (directory / "stdout.txt").open("wb") as out, (directory / "stderr.txt").open("wb") as err:
            process = subprocess.Popen(command, cwd=cwd, stdout=out, stderr=err, start_new_session=True, env=env)
            try:
                process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
                raise
        result = {"status": "command_succeeded" if process.returncode == 0 else "command_failed",
                  "returncode": process.returncode}
    except subprocess.TimeoutExpired:
        result = {"status": "timeout", "returncode": None}
    except OSError as exc:
        result = {"status": "environment_error", "returncode": None, "error_type": type(exc).__name__}
    result.update(command=command, seconds=time.monotonic() - started)
    if setup is not None:
        from .feedback import collect_feedback
        result["activation"] = collect_feedback(candidate, directory, setup)
    write_json(directory / "result.json", result)
    return result


def execute(prepared, response, output, command, *, timeout=300, run_baseline=True):
    """Run the supplied test command, never one suggested by the model/history.

    A zero return code is not evidence of test collection or a correct oracle.
    Raw logs and separate baseline results remain available for review.
    """
    import json
    response = parse_response(json.dumps({k: response[k] for k in
        ("decision", "reason", "distinction", "tests", "existing_test_ids")}), prepared, response["candidate_id"])
    output = Path(output).resolve()
    repository = Path(prepared["repository"]).resolve()
    if output == repository or repository in output.parents:
        raise ValueError("execution_output_must_be_outside_subject_repository")
    if response["decision"] not in {"gap", "selection_problem"}:
        raise ValueError("nothing_to_execute")
    if timeout <= 0:
        raise ValueError("timeout_must_be_positive")
    for path, expected in prepared["source_receipts"].items():
        source = repository / path
        if not source.is_file() or hashlib.sha256(source.read_bytes()).hexdigest() != expected:
            raise ValueError("prepared_source_changed:" + path)
    output.mkdir(parents=True, exist_ok=False)
    workspace = output / "repository"
    _copy_repository(repository, workspace)
    candidate = next(c for c in prepared["candidates"] if c["id"] == response["candidate_id"])
    original_paths = [prepared["tests"][t]["span"]["path"] for t in candidate["test_ids"]
                      if prepared["tests"][t]["origin"] == "repository"]
    if response["decision"] == "selection_problem":
        chosen = [prepared["tests"][t] for t in response["existing_test_ids"]]
        if any(t["origin"] != "repository" for t in chosen):
            raise ValueError("historical_test_requires_explicit_replay_materialization")
        paths = [t["span"]["path"] for t in chosen]
        run = _run(_command(command, paths), workspace, output / "selection", timeout, candidate)
        result = {"decision": "selection_problem", "execution": run}
    else:
        baseline = (_run(_command(command, original_paths), workspace, output / "baseline", timeout, candidate)
                    if original_paths and run_baseline else {"status": "baseline_not_requested" if not run_baseline else "no_original_repository_test_selected", "returncode": None})
        # Baseline tests can mutate fixture files. Generate into a fresh copy.
        shutil.rmtree(workspace)
        _copy_repository(repository, workspace)
        for edit in response["tests"]:
            path = workspace / edit["path"]
            if not path.resolve().is_relative_to(workspace):
                raise ValueError("test_path_leaves_workspace")
            if edit["mode"] == "new" and path.exists():
                raise ValueError("new_test_already_exists:" + edit["path"])
            path.parent.mkdir(parents=True, exist_ok=True)
            if edit["mode"] == "append":
                path.write_text(path.read_text() + "\n\n" + edit["code"] + "\n")
            else:
                path.write_text(edit["code"] + "\n")
        paths = [t["path"] for t in response["tests"]]
        augmented = _run(_command(command, paths), workspace, output / "augmented", timeout, candidate)
        result = {"decision": "gap", "baseline": baseline, "augmented": augmented}
    result.update(candidate_id=response["candidate_id"],
                  interpretation="Execution logs require test-collection and contract review. A candidate gap, test failure and patch defect are different outcomes.")
    write_json(output / "result.json", result)
    return result
