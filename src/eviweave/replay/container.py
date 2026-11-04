"""Disposable Docker sessions used by chronological replay and test execution."""
from contextlib import contextmanager
import json
from pathlib import Path
import subprocess
import uuid

from ..artifacts import write_json


ENV = {'PAGER': 'cat', 'MANPAGER': 'cat', 'LESS': '-R',
       'PIP_PROGRESS_BAR': 'off', 'TQDM_DISABLE': '1'}
COMMAND_SCRIPT = Path(__file__).with_name('command_guest.py').read_text()


class Container:
    def __init__(self, name, image_id, head, output):
        self.name, self.image_id, self.base_commit = name, image_id, head
        self.output = Path(output)
        self.scratch = '/tmp/' + name

    @staticmethod
    def docker(arguments, *, input_bytes=None, timeout=60, check=True):
        process = subprocess.run(['docker', *arguments], input=input_bytes, capture_output=True, timeout=timeout)
        if check and process.returncode:
            raise RuntimeError(f'docker exited {process.returncode}: ' + process.stderr.decode(errors='replace'))
        return process

    def control(self, argv, *, input_bytes=None, timeout=60):
        return self.docker(['exec', '-i', self.name, *argv], input_bytes=input_bytes, timeout=timeout)

    def copy_from(self, source, destination):
        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        self.docker(['cp', self.name + ':' + source, str(destination)])
        return destination

    def copy_to(self, source, destination):
        self.control(['mkdir', '-p', str(Path(destination).parent)])
        self.docker(['cp', str(source), self.name + ':' + destination])

    def run(self, command, label, *, timeout=30, workdir='/app', env=None, observer_script=None):
        directory = self.output / 'calls' / label
        directory.mkdir(parents=True)
        (directory / 'command.sh').write_text(command)
        request = {'command': command, 'timeout': timeout, 'workdir': workdir,
                   'env': {**ENV, **(env or {})}, 'output': self.scratch + '/' + label + '.output'}
        if observer_script is not None:
            request.update(root='/app',trace_directory=self.scratch+'/'+label+'.trace')
        process = self.control(['python3', '-I', '-c', observer_script if observer_script is not None else COMMAND_SCRIPT],
                               input_bytes=json.dumps(request).encode(), timeout=timeout + 30)
        result = json.loads(process.stdout)
        self.copy_from(request['output'], directory / 'output.bin')
        if observer_script is not None:
            self.copy_from(request['trace_directory'],directory/'trace')
            result['trace']=str(directory/'trace')
            result['trace_guest_directory']=request['trace_directory']
        result.update(id=label, command=command, shell='/bin/sh', working_directory=workdir,
                      timeout_seconds=timeout, env=request['env'], output=str(directory / 'output.bin'))
        saved={**result,'output':'output.bin'}
        if observer_script is not None:saved['trace']='trace'
        write_json(directory / 'result.json', saved)
        return result

    def checkpoint(self):
        self.control(['rm','-rf',self.scratch],timeout=180)
        image_id = self.docker(['commit', self.name], timeout=180).stdout.decode().strip()
        head = self.control(['git', '-c', 'safe.directory=/app', '-C', '/app', 'rev-parse', 'HEAD']).stdout.decode().strip()
        return {'image_id': image_id, 'head': head}


@contextmanager
def open_container(image, head, output, *, cpus=2, memory='8g', pids_limit=1024, trace_commands=False,
                   network='none'):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    image_id = Container.docker(['image', 'inspect', '--format', '{{.Id}}', image]).stdout.decode().strip()
    name = 'eviweave-' + uuid.uuid4().hex[:16]
    tracing=['--cap-add','SYS_PTRACE'] if trace_commands else []
    Container.docker(['run', '--detach', '--init', '--name', name, '--network', network,
                      '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges:true',
                      *tracing,
                      '--cpus', str(cpus), '--memory', memory, '--pids-limit', str(pids_limit),
                      '--entrypoint', 'sleep', image_id, 'infinity'])
    runtime = Container(name, image_id, head, output)
    try:
        actual = runtime.control(['git', '-c', 'safe.directory=/app', '-C', '/app', 'rev-parse', 'HEAD']).stdout.decode().strip()
        assert actual == head, f'Expected HEAD {head}, got {actual}'
        runtime.control(['mkdir', '-p', runtime.scratch])
        write_json(output / 'container.json', {'name': name, 'image_id': image_id, 'head': head,
                                             'network': network, 'host_mounts': []})
        yield runtime
    finally:
        Container.docker(['rm', '-f', name])
