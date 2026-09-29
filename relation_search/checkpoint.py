"""Small immutable stage receipts for resumable local search."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    return json.loads(Path(path).read_text())


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.tmp')
    temporary.write_text(json.dumps(value, sort_keys=True, indent=2) + '\n')
    temporary.replace(path)


def start(directory, request):
    directory = Path(directory)
    marker = directory/'stage.json'
    if directory.exists() and marker.exists():
        if read(marker) != request:
            raise ValueError('Resume inputs or algorithm changed: ' + str(directory))
    elif directory.exists() and any(directory.iterdir()):
        raise ValueError('Unowned nonempty stage directory: ' + str(directory))
    directory.mkdir(parents=True, exist_ok=True)
    write(marker, request)


def seal(directory, result, name='checkpoint.json'):
    directory = Path(directory)
    files = {str(path.relative_to(directory)): digest(path)
             for path in sorted(directory.rglob('*'))
             if path.is_file() and path.name not in {name, '.run.lock'}
             and not path.name.endswith('.tmp')}
    value = {'files_sha256': files, 'result': result}
    write(directory/name, value)
    return value


def completed(directory, name='checkpoint.json'):
    directory = Path(directory)
    path = directory/name
    if not path.exists():
        return None
    value = read(path)
    for relative, checksum in value['files_sha256'].items():
        target = directory/relative
        if not target.is_file() or digest(target) != checksum:
            raise ValueError('Completed checkpoint artifact changed: ' + str(target))
    return value['result']
