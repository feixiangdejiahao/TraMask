"""Read-only source observer. Executed with python -I inside a replay container.

Only the JSON request and response cross the container boundary. No imports of
subject code, test collection, build, or additional subject execution occur.
"""
import base64
import hashlib
import json
import os
import sys


BLOCKED = {'.git', '.aws', '.codex', '.agents', 'node_modules', '.venv', 'venv',
           '__pycache__', '.pytest_cache', '.mypy_cache', '.cache', 'target'}
CONFIGS = {'pyproject.toml', 'pytest.ini', 'setup.cfg', 'setup.py', 'tox.ini',
           'package.json', 'package-lock.json', 'pnpm-lock.yaml', 'yarn.lock',
           'go.mod', 'go.sum', 'go.work', 'Cargo.toml', 'Cargo.lock',
           'Makefile', 'justfile', 'tsconfig.json', '.mocharc.json'}
TEST_DIRS = {'test', 'tests', 'spec', 'specs', '__tests__', 'fixtures', '__fixtures__', 'testdata'}


def collect(request):
    root = os.path.abspath(request.get('root', '/app'))
    known = set(request.get('known_blobs', []))
    extra = set(request.get('extra_paths', []))
    files, blobs = [], {}
    def allowed(path):
        parts = path.split(os.sep)
        return not any(x in BLOCKED or x == '.env' or x.startswith('.env.') for x in parts)

    def interesting(path):
        if request.get('all_sources',False):return True
        rel = os.path.relpath(path, root)
        parts, name = rel.split(os.sep), os.path.basename(path)
        return (bool(set(parts[:-1]) & TEST_DIRS) or name in CONFIGS
                or name == 'conftest.py' or name.startswith(('test_', 'test-', 'test.', 'requirements', 'jest.config', 'vitest.config'))
                or name.endswith(('_test.go', '_test.py', '.rs'))
                or any(x in name for x in ('.test.', '.spec.')))

    names = set()
    for directory, dirs, entries in os.walk(root, followlinks=False):
        dirs[:] = sorted(x for x in dirs if allowed(os.path.join(directory, x)) and not os.path.islink(os.path.join(directory, x)))
        names.update(os.path.join(directory, x) for x in entries if interesting(os.path.join(directory, x)))
    for path in extra:
        path = os.path.normpath(path)
        if path == root or path.startswith(root + '/') or path.startswith('/tmp/'):
            names.add(path)
    for path in sorted(names):
        if not allowed(path):
            continue
        row = {'path': path}
        if not os.path.lexists(path):
            row.update(kind='missing')
        elif os.path.islink(path):
            row.update(kind='symlink', target=os.readlink(path))
        elif os.path.isfile(path):
            with open(path, 'rb') as stream:
                raw = stream.read()
            digest = hashlib.sha256(raw).hexdigest()
            row.update(kind='file', sha256=digest)
            if digest not in known:
                blobs[digest] = base64.b64encode(raw).decode('ascii')
        else:
            continue
        files.append(row)
    return {'files': files, 'blobs': blobs}


if __name__ == '__main__':
    print(json.dumps(collect(json.load(sys.stdin)), ensure_ascii=True))
