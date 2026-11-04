"""Run builds and a test command in a fresh submitted-checkpoint clone."""
import json
from pathlib import Path
import shlex

from .artifacts import write_json
from .replay.container import open_container
from .replay.state import SCRIPT


def patch_paths(patch):
    paths = []
    for line in patch.splitlines():
        if line.startswith(('+++ ', '--- ')) and line[4:] != '/dev/null':
            path = shlex.split(line[4:])[0]
            paths.append('/app/' + path[2:])
    return sorted(set(paths))


def snapshot_paths(runtime, paths):
    request = {'operation': 'files', 'paths': paths}
    process = runtime.control(['python3', '-I', '-c', SCRIPT], input_bytes=json.dumps(request).encode())
    return json.loads(process.stdout)


def run_in_checkpoint(checkpoint, command, out, *, workdir='/app', env=None,
                      build_commands=(), timeout=120, source_paths=(), files=()):
    out = Path(out).resolve()
    out.mkdir(parents=True)
    plan = {'checkpoint': checkpoint, 'command': command, 'workdir': workdir,
            'env': env or {}, 'build_commands': list(build_commands),
            'timeout': timeout, 'source_paths': list(source_paths),
            'files': [{'source':str(source),'destination':destination} for source,destination in files]}
    write_json(out / 'plan.json', plan)
    result = {'status': 'completed', 'checkpoint': checkpoint, 'builds': [], 'execution': None}
    with open_container(checkpoint['image_id'], checkpoint['head'], out / 'container') as runtime:
        for source, destination in files:
            runtime.copy_to(source, destination)
        before = snapshot_paths(runtime, list(source_paths))
        for index, build in enumerate(build_commands):
            record = runtime.run(build, 'build_' + str(index), workdir=workdir, env=env, timeout=timeout)
            result['builds'].append(record)
            if record['status'] != 'completed' or record['returncode'] != 0:
                result['status'] = 'build_failed'
                break
        if result['status'] == 'completed':
            result['execution'] = runtime.run(command, 'test', workdir=workdir, env=env, timeout=timeout)
            result['status'] = result['execution']['status']
        after = snapshot_paths(runtime, list(source_paths))
    result['sources'] = {'before': before, 'after': after, 'unchanged': before == after}
    write_json(out / 'result.json', result)
    return result
