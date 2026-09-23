"""Standard-library-only fresh-container executor for a frozen artifact."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time


def main():
    request = json.load(sys.stdin)
    manifest = request["manifest"]
    logs = Path("/combination-logs")
    report = {"stage": "base_check", "returncode": None}
    started = time.monotonic()
    try:
        head = subprocess.run(["git", "rev-parse", "HEAD"], cwd="/app", capture_output=True,
                              text=True, check=True).stdout.strip()
        report["base_commit"] = head
        if head != request["base_commit"]:
            raise ValueError("Container repository base commit does not match case registry")
        if request["program"] != "base":
            report["stage"] = "patch"
            patch = subprocess.run(["git", "apply", "--whitespace=nowarn", "/implementation.patch"],
                                   cwd="/app", capture_output=True, text=True)
            (logs / "patch.stdout").write_text(patch.stdout)
            (logs / "patch.stderr").write_text(patch.stderr)
            if patch.returncode:
                raise ValueError("Implementation patch could not be applied")
        report["stage"] = "artifact_copy"
        copied = []
        for entry in manifest["files"]:
            source = Path("/artifact") / entry["source"]
            if hashlib.sha256(source.read_bytes()).hexdigest() != entry["sha256"]:
                raise ValueError("Frozen artifact hash mismatch")
            target = Path("/app") / entry["target"]
            if not target.resolve().is_relative_to(Path("/app")):
                raise ValueError("Artifact target escapes repository")
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
            copied.append({"target": entry["target"], "sha256": entry["sha256"]})
        report["files"] = copied
        environment = dict(os.environ)
        environment["COMBINATION_REPORT_DIR"] = str(logs)
        # Repository images already contain dependencies. Never install/download here.
        environment["PIP_NO_INDEX"] = "1"
        environment["GOPROXY"] = "off"
        report["stage"] = "test"
        with (logs / "stdout.txt").open("w") as stdout, (logs / "stderr.txt").open("w") as stderr:
            child = subprocess.Popen(["bash", "-lc", manifest["command"]], cwd="/app",
                                     stdout=stdout, stderr=stderr, env=environment,
                                     start_new_session=True)
            try:
                report["returncode"] = child.wait(timeout=int(manifest.get("timeout", 180)))
            except subprocess.TimeoutExpired:
                os.killpg(child.pid, signal.SIGKILL)
                child.wait()
                report["timed_out"] = True
                report["error"] = "Test command exceeded timeout"
        report["stage"] = "finished" if "error" not in report else "timeout"
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        report["error"] = str(exc)
    finally:
        report["elapsed_seconds"] = time.monotonic() - started
        (logs / "process.json").write_text(json.dumps(report, indent=2) + "\n")
        for path in [logs, *logs.rglob("*")]:
            if not path.is_symlink():
                os.chown(path, request["uid"], request["gid"])
    print(json.dumps(report))
    raise SystemExit(1 if "error" in report else 0)


if __name__ == "__main__":
    main()
