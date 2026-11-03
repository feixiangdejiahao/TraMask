"""Git state, command execution and an independently importable replay package."""
from contextlib import contextmanager
import json
from pathlib import Path
import subprocess
import sys

import pytest

from eviweave.replay.command_guest import execute
from eviweave.replay.state_guest import collect, git, gitlink_state


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / 'repo'
    root.mkdir()
    git(root, 'init', '-q')
    git(root, 'config', 'user.name', 'Fixture')
    git(root, 'config', 'user.email', 'fixture@example.invalid')
    (root / 'kept.py').write_text('old\n')
    (root / 'deleted.py').write_text('deleted\n')
    (root / '.gitattributes').write_text('*.txt text eol=crlf\n')
    git(root, 'add', '.')
    git(root, 'commit', '-qm', 'base')
    base = git(root, 'rev-parse', 'HEAD').decode().strip()
    return root, base


def test_submitted_tree_literal_bytes_modes_links_and_deletions(repo, tmp_path):
    root, base = repo
    (root / 'kept.py').write_text('new\n')
    (root / 'deleted.py').unlink()
    (root / 'added.txt').write_bytes(b'line\r\n')
    (root / 'link').symlink_to('kept.py')
    (root / 'executable.py').write_text('pass\n')
    (root / 'executable.py').chmod(0o755)
    git(root, 'add', '.')
    git(root, 'commit', '-qm', 'submitted')
    patch = tmp_path / 'model.patch'
    patch.write_bytes(git(root, 'diff', '--binary', base, 'HEAD'))
    index_before = (root / '.git/index').read_bytes()
    head_before = git(root, 'rev-parse', 'HEAD')
    result = collect(root, base, patch, tmp_path)
    assert not result['mismatches']
    assert result['head_tree'] == result['expected_tree']
    assert result['actual_index'] == result['expected']
    assert (root / '.git/index').read_bytes() == index_before
    assert git(root, 'rev-parse', 'HEAD') == head_before
    # A misleading clean filter must not erase an actual byte difference.
    git(root, 'config', 'filter.hide.clean', 'printf new\\n')
    (root / '.git/info/attributes').write_text('kept.py filter=hide\n')
    (root / 'kept.py').write_text('wrong\n')
    result = collect(root, base, patch, tmp_path)
    assert [r['path'] for r in result['mismatches']] == ['kept.py']


def test_worktree_equal_to_patch_does_not_imply_submitted_commit_matches(repo, tmp_path):
    root, base = repo
    (root / 'kept.py').write_text('new\n')
    patch = tmp_path / 'model.patch'
    patch.write_bytes(git(root, 'diff', '--binary', base))
    result = collect(root, base, patch, tmp_path)
    assert not result['mismatches']
    assert result['head_tree'] != result['expected_tree']
    assert result['actual_index'] != result['expected']


def test_file_directory_and_symlink_transitions_match_git_path_semantics(repo, tmp_path):
    root, _ = repo
    (root / 'directory').mkdir()
    (root / 'directory/child').write_text('old\n')
    git(root, 'add', '.')
    git(root, 'commit', '-qm', 'directory base')
    base = git(root, 'rev-parse', 'HEAD').decode().strip()
    (root / 'directory/child').unlink()
    (root / 'directory').rmdir()
    (root / 'deleted.py').unlink()
    (root / 'deleted.py').mkdir()
    (root / 'deleted.py/child').write_text('old\n')
    (root / 'directory').symlink_to('deleted.py')
    git(root, 'add', '.')
    git(root, 'commit', '-qm', 'transitions')
    patch = tmp_path / 'model.patch'
    patch.write_bytes(git(root, 'diff', '--binary', base, 'HEAD'))
    result = collect(root, base, patch, tmp_path)
    assert not result['mismatches'] and result['expected_tree'] == result['head_tree']


def test_submodule_literal_changes_remain_visible(repo, tmp_path):
    root, _ = repo
    nested = root / 'vendor'
    nested.mkdir()
    git(nested, 'init', '-q')
    (nested / 'source.py').write_text('original\n')
    git(nested, 'add', '.')
    git(nested, '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid', 'commit', '-qm', 'nested')
    git(root, 'add', 'vendor')
    git(root, 'commit', '-qm', 'submodule')
    base = git(root, 'rev-parse', 'HEAD').decode().strip()
    patch = tmp_path / 'model.patch'
    patch.write_bytes(b'')
    original = gitlink_state(root)
    assert collect(root, base, patch, tmp_path)['gitlinks'] == original
    (nested / 'source.py').write_text('changed\n')
    actual = collect(root, base, patch, tmp_path)['gitlinks']
    assert actual != original and actual['vendor']['files'] != original['vendor']['files']


def test_raw_command_executes_its_entire_compound_and_records_timeout(tmp_path):
    request = {'command': "printf before; printf 'COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT'; printf after",
               'workdir': str(tmp_path), 'env': {}, 'timeout': 5, 'output': str(tmp_path / 'output.bin')}
    result = execute(request)
    assert result['returncode'] == 0
    assert (tmp_path / 'output.bin').read_bytes() == b'beforeCOMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUTafter'
    request.update(command='printf started; sleep 5', timeout=0.1)
    result = execute(request)
    assert result['timed_out'] and result['status'] == 'timeout'
    assert (tmp_path / 'output.bin').read_bytes() == b'started'


def test_replay_import_and_cli_need_only_the_copied_package_and_standard_library(tmp_path):
    import shutil
    source = Path(__file__).resolve().parents[1] / 'src/eviweave'
    shutil.copytree(source, tmp_path / 'eviweave', ignore=shutil.ignore_patterns('__pycache__'))
    result = subprocess.run([sys.executable, '-S', '-m', 'eviweave.replay', '--help'],
                             cwd=tmp_path, capture_output=True, text=True, check=True)
    assert '--input-directory' in result.stdout
    # Optional collection parsers do not get imported by standalone replay.
    code = 'import sys; import eviweave.replay; print("\\n".join(sys.modules))'
    result = subprocess.run([sys.executable, '-S', '-c', code], cwd=tmp_path,
                             capture_output=True, text=True, check=True)
    assert not any(name in result.stdout for name in ('tramask', 'fragment_reuse', 'tree_sitter', 'context_recovery'))


def test_replay_and_collection_run_together_on_a_real_git_fixture(repo, tmp_path, monkeypatch):
    import shutil
    from eviweave.artifacts import read_json, write_json
    from eviweave.collection import collect_tests
    from eviweave.replay import core

    root, _ = repo
    (root / 'test_x.py').write_text('def test_x(): assert True\n')
    git(root, 'add', 'test_x.py')
    git(root, 'commit', '-qm', 'test base')
    base = git(root, 'rev-parse', 'HEAD').decode().strip()
    (root / 'kept.py').write_text('new\n')
    git(root, 'commit', '-qam', 'expected final')
    patch = git(root, 'diff', '--binary', base, 'HEAD')
    git(root, 'reset', '--hard', base)
    commands = ["printf 'new\\n' > kept.py && git add kept.py && git commit -qm final",
                sys.executable + ' -m pytest test_x.py -vv']
    raw = tmp_path / 'raw'
    raw.mkdir()
    (raw / 'instruction.md').write_text('Synthetic task')
    (raw / 'task.toml').write_text('[metadata]\nbase_commit_hash="' + base + '"\n[environment]\ndocker_image="fixture"\n')
    (raw / 'model.patch').write_bytes(patch)
    write_json(raw / 'trajectory.json', {'steps': [
        {'step_id': i, 'tool_calls': [{'function_name': 'bash', 'arguments': {'command': command}}],
         'observation': {'results': [{'content': json.dumps({'returncode': 0, 'output': ''})}]}}
        for i, command in enumerate(commands)]})
    seen = []

    class LocalSession:
        def __init__(self, output, head):
            self.output, self.base_commit = Path(output), head
            self.output.mkdir(parents=True)
            self.name, self.image_id = 'fixture', 'fixture-image'
            self.scratch = str(tmp_path / 'scratch')
            Path(self.scratch).mkdir(exist_ok=True)

        def control(self, argv, *, input_bytes=None, **kwargs):
            if input_bytes is None:
                return subprocess.run(argv, capture_output=True, check=True)
            request = json.loads(input_bytes)
            request['root'] = str(root)
            if 'extra_paths' in request:
                request['extra_paths'] = [p.replace('/app/', str(root) + '/', 1) for p in request['extra_paths']]
            process = subprocess.run([sys.executable, '-I', '-c', argv[-1]],
                                     input=json.dumps(request).encode(), capture_output=True, check=True)
            if 'known_blobs' in request:
                snapshot = json.loads(process.stdout)
                for row in snapshot['files']:
                    row['path'] = row['path'].replace(str(root), '/app', 1)
                process.stdout = json.dumps(snapshot).encode()
            return process

        def run(self, command, label, *, observer_script):
            seen.append(command)
            directory = self.output / 'calls' / label
            directory.mkdir(parents=True)
            (directory / 'command.sh').write_text(command)
            guest=tmp_path/'guest-traces'/label;guest.parent.mkdir(exist_ok=True)
            request={'command': command, 'workdir': str(root), 'env': {}, 'timeout': 30,
                     'root':str(root),'trace_directory':str(guest),'output':str(directory/'output.bin')}
            process=subprocess.run([sys.executable,'-I','-c',observer_script],input=json.dumps(request).encode(),capture_output=True,check=True)
            shutil.copytree(guest,directory/'trace')
            return dict(json.loads(process.stdout),id=label,trace=str(directory/'trace'),trace_guest_directory=str(guest))

        def checkpoint(self):
            return {'image_id': self.image_id, 'head': git(root, 'rev-parse', 'HEAD').decode().strip()}

        def copy_to(self, source, destination):
            shutil.copyfile(source, destination)

    @contextmanager
    def local_container(image, head, output, **resources):
        yield LocalSession(output, head)

    monkeypatch.setattr(core, 'open_container', local_container)
    out = tmp_path / 'run'
    result = collect_tests({'id': 'synthetic', 'image': 'fixture', 'base_commit': base}, raw, out)
    assert seen == commands and result['state_validation_passed']
    manifest = read_json(result['step_a']['manifest'])
    retained = [u for u in manifest['tests'] if u['retained_at_submission']]
    assert len(retained) == 1
    assert retained[0]['execution_status'] == 'named_report_observed'
    from eviweave.history import history_records, read_context
    records = history_records(result['step_a']['manifest'])
    source = next(r for r in records if r['text'] == 'def test_x(): assert True\n')
    assert read_context(source['source']) == 'def test_x(): assert True\n'
    assert seen == commands
    from eviweave.slicing import slice_targets
    slice_targets(result['step_a']['manifest'], out / 'slicing')
    moved = tmp_path / 'moved-run'
    out.rename(moved)
    manifest_path = moved / 'tests/manifest.json'
    records = history_records(manifest_path)
    assert any(read_context(r['source']) == 'def test_x(): assert True\n' for r in records)
    from eviweave.slicing import TrajectorySlicer
    from eviweave.targets import targets_from_manifest
    targets_from_manifest(manifest_path)
    slicer = TrajectorySlicer(manifest_path)
    saved = read_json(moved / 'slicing/targets.json')
    source = next(r for r in saved['records'] if r['text'] == 'def test_x(): assert True\n')
    assert read_context(source['source'],base=moved/'slicing') == source['text']
    assert slicer.source(source['source'],base=moved/'slicing')[2] == source['text'].encode()
    action = next(e for e in slicer.trajectory.events.values() if e['kind'] == 'action')
    assert Path(action['command']).exists() and Path(action['replay_output']).exists()
    detached = tmp_path / 'detached-runtime'
    (moved / 'runtime').rename(detached)
    (moved / 'runtime').symlink_to(detached, target_is_directory=True)
    records = history_records(manifest_path)
    output = next(r for r in records if r['source'].endswith('/output.bin') and r['text'])
    slicer = TrajectorySlicer(manifest_path)
    assert output['source'] in slicer.material_refs
    views = slicer.location(output['source'], 0, len(output['text'][0].encode()))
    assert views[0]['mode'] == 'data'
