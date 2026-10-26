"""An escaped child retaining stdout must not prevent later replay actions."""
import json
import os
from pathlib import Path
import shlex
import signal
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from tramask_pilot.submission_replay import EXECUTE


def test_timeout_preserves_partial_output_without_waiting_for_detached_child(tmp_path):
    pid_file = tmp_path / "detached.pid"
    child = "import time; time.sleep(30)"
    action = (
        "import subprocess,sys,time; "
        f"p=subprocess.Popen([sys.executable,'-c',{child!r}],start_new_session=True); "
        f"open({str(pid_file)!r},'w').write(str(p.pid)); "
        "print('before-timeout',flush=True); time.sleep(30)"
    )
    script = (EXECUTE.replace("cwd='/app'", "cwd=" + repr(str(tmp_path)))
              .replace("communicate(timeout=30)", "communicate(timeout=0.3)")
              .replace("communicate(timeout=5)", "communicate(timeout=0.1)"))
    output = tmp_path / "output.bin"
    request = {"command": shlex.join([sys.executable, "-c", action]), "env": {}, "output": str(output)}
    start = time.monotonic()
    try:
        run = subprocess.run([sys.executable, "-c", script], input=json.dumps(request),
                             capture_output=True, text=True, timeout=3, check=True)
        result = json.loads(run.stdout)
        assert result["timed_out"] is True
        assert result["output_drain_incomplete"] is True
        assert output.read_bytes() == b"before-timeout\n"
        assert time.monotonic() - start < 2
        # The replay observer must leave the escaped group alone.
        os.kill(int(pid_file.read_text()), 0)
    finally:
        if pid_file.exists():
            try:
                os.kill(int(pid_file.read_text()), signal.SIGKILL)
            except ProcessLookupError:
                pass
