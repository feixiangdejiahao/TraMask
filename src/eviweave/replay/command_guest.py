"""Run a command in the subject container; no host shell evaluates its text."""
import json
import os
import signal
import subprocess
import sys
import time


def execute(request):
    started = time.monotonic()
    process = subprocess.Popen(request['command'], shell=True, cwd=request['workdir'],
                               env={**os.environ, **request['env']}, stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT, start_new_session=True)
    timed_out = False
    try:
        output, _ = process.communicate(timeout=request['timeout'])
    except subprocess.TimeoutExpired:
        timed_out = True
        os.killpg(process.pid, signal.SIGKILL)
        # Detached descendants can retain the pipe after the original shell is
        # killed. Keep partial output rather than waiting for their lifetime.
        try:
            output, _ = process.communicate(timeout=5)
        except subprocess.TimeoutExpired as error:
            output = error.output or b''
            process.stdout.close()
    with open(request['output'], 'wb') as stream:
        stream.write(output)
    return {'returncode': -1 if timed_out else process.returncode, 'timed_out': timed_out,
            'status': 'timeout' if timed_out else 'completed',
            'elapsed_seconds': time.monotonic() - started, 'output_bytes': len(output)}


if __name__ == '__main__':
    print(json.dumps(execute(json.load(sys.stdin))))
