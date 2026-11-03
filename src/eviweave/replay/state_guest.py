"""Compare submitted Git state with base + patch in a separate repository."""
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile


def git(root, *args, input_bytes=None):
    process = subprocess.run(['git', '-c', 'safe.directory=*', '-c', 'core.fsmonitor=false',
                              '-C', str(root), *args], input=input_bytes, capture_output=True,
                             env={**os.environ, 'GIT_OPTIONAL_LOCKS': '0',
                                  'GIT_CONFIG_NOSYSTEM': '1', 'GIT_CONFIG_GLOBAL': os.devnull})
    if process.returncode:
        raise RuntimeError(process.stderr.decode(errors='replace'))
    return process.stdout


def entries(root, *args):
    result = {}
    for row in git(root, *args, '-z').split(b'\0'):
        if row:
            header, path = row.split(b'\t', 1)
            mode, _, oid = header.split()
            # ls-files gives mode/oid/stage; ls-tree gives mode/type/oid.
            result[os.fsdecode(path)] = {'mode': mode.decode(),
                                        'oid': (header.split()[1] if args[0] == 'ls-files' else oid).decode()}
            if args[0] == 'ls-files' and oid != b'0':
                result[os.fsdecode(path)]['stage'] = int(oid)
    return result


def file_state(path):
    if not os.path.lexists(path):
        return {'kind': 'missing'}
    mode = os.lstat(path).st_mode
    if stat.S_ISLNK(mode):
        return {'kind': 'symlink', 'target': os.readlink(path), 'mode': '120000'}
    if stat.S_ISDIR(mode):
        return {'kind': 'directory'}
    return {'kind': 'file', 'mode': '100755' if mode & stat.S_IXUSR else '100644',
            'sha256': hashlib.sha256(Path(path).read_bytes()).hexdigest()}


def working_state(root, path):
    # A Git path ends at an ancestor file or symlink. Bytes reached through a
    # replacement directory symlink are not the old tracked descendant.
    parent = Path(root)
    for part in path.split('/')[:-1]:
        parent = parent / part
        if parent.is_symlink() or not parent.is_dir():
            return {'kind': 'missing'}
    return file_state(Path(root) / path)


def gitlink_state(root):
    """Record original-image submodule contents, including vendored worktrees."""
    links = {}
    for path, entry in entries(root, 'ls-tree', '-r', 'HEAD').items():
        if entry['mode'] != '160000':
            continue
        directory = Path(root) / path
        files = {}
        for parent, dirs, names in os.walk(directory, followlinks=False):
            dirs[:] = sorted(d for d in dirs if d != '.git')
            for name in sorted(names + [d for d in dirs if os.path.islink(Path(parent) / d)]):
                if name != '.git':
                    target = Path(parent) / name
                    files[str(target.relative_to(directory))] = file_state(target)
        initialized = (directory / '.git').exists()
        links[path] = {**entry, 'files': files, 'kind': file_state(directory)['kind'],
                       'head': git(directory, 'rev-parse', 'HEAD').decode().strip() if initialized else None,
                       'status': git(directory, 'status', '--porcelain=v1').decode() if initialized else None}
    return links


def collect(root, base_commit, patch, scratch_parent):
    root = Path(root)
    head = git(root, 'rev-parse', 'HEAD').decode().strip()
    actual_index = entries(root, 'ls-files', '--stage')
    # The clone has its own index, worktree, attributes and objects. The
    # submitted patch is never applied to the replay's files or real index.
    with tempfile.TemporaryDirectory(prefix='expected-', dir=scratch_parent) as scratch:
        expected_root = Path(scratch) / 'repo'
        git(root, 'clone', '--shared', '--no-checkout', '--quiet', str(root), str(expected_root))
        git(expected_root, 'read-tree', base_commit)
        base = entries(expected_root, 'ls-files', '--stage')
        if Path(patch).stat().st_size:
            git(expected_root, 'apply', '--cached', '--binary', '--whitespace=nowarn', str(patch))
        expected = entries(expected_root, 'ls-files', '--stage')
        expected_tree = git(expected_root, 'write-tree').decode().strip()
        git(expected_root, 'checkout-index', '--all', '--force')
        mismatches = []
        for path in sorted(set(base) | set(expected) | set(actual_index)):
            if path in expected and expected[path]['mode'] == '160000':
                continue
            want = working_state(expected_root, path)
            have = working_state(root, path)
            # Deleted files may leave an implicit parent directory behind.
            matched = (have['kind'] in {'missing', 'directory'} if path not in expected else want == have)
            if not matched:
                mismatches.append({'path': path, 'expected': want, 'actual': have})
        return {'head': head, 'expected_tree': expected_tree,
                'head_tree': git(root, 'rev-parse', 'HEAD^{tree}').decode().strip(),
                'expected': expected, 'actual_index': actual_index, 'mismatches': mismatches,
                'gitlinks': gitlink_state(root)}


if __name__ == '__main__':
    request = json.load(sys.stdin)
    root = request.get('root', '/app')
    if request['operation'] == 'files':
        value = {path: file_state(path) for path in request['paths']}
    elif request['operation'] == 'gitlinks':
        value = gitlink_state(root)
    else:
        value = collect(root, request['base_commit'], request['patch'], request['scratch_parent'])
    print(json.dumps(value))
