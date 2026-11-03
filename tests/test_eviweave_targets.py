"""D uses real A-shaped files, parsers, provenance and saved shell commands."""
import hashlib
import json
from pathlib import Path
import shlex
import subprocess
import sys

import pytest

from eviweave.artifacts import read_json, resolve_references, write_json
from eviweave.blobs import BlobStore
from eviweave.history import history_records, load_materials, read_source_bytes
from eviweave.pre_slice import covered
from eviweave.shell import inline_sources
from eviweave.targets import locate_targets, read_target_source, targets_from_manifest


def file_material(path, text, source):
    raw = text.encode()
    return {'source': str(source), 'kind': 'file', 'path': path, 'text': text, 'raw': raw,
            'sha256': hashlib.sha256(raw).hexdigest()}


@pytest.fixture
def collected(tmp_path):
    replay = tmp_path / 'replay'
    tests = replay / 'tests'
    blobs = tests / 'blobs'
    BlobStore(blobs).create()

    def version(path, text):
        raw = text.encode()
        digest = hashlib.sha256(raw).hexdigest()
        BlobStore(blobs).put(raw)
        return {'path': path, 'sha256': digest}

    old = version('/app/lib.py', 'def legacy_only(x):\n    return x.old\n')
    current = version('/app/lib.py', 'def changed(x):\n    return x.closed\n')
    text = ('from first_api import Client\n\ndef test_send():\n    marker = "中文"\n'
            + '    # keep full source context\n' * 250
            + '    a.send(1)\n    b.send(2)\n    a.resume()\n'
            + '    assert a.closed and a.ready and a.info["current_state"]\n'
            + '\ndef test_unrelated():\n    a.unrelated_call()\n')
    text = text.replace('\n', '\r\n')
    first = version('/app/test_first.py', text)
    second = version('/app/test_second.py', text.replace('first_api', 'second_api'))
    javascript = version('/app/tests.test.ts', "it('selected',()=>{c.emit()}); it('other',()=>{c.unrelated_js()});")
    old_test = version('/app/test_first.py', text.replace('a.resume()', 'a.old_resume()'))
    broken = version('/app/test_broken.py', 'def broken(:\n    a.send(1)\n')
    data = version('/app/data.json', '{"duration": 304}\n')
    orphan = version('/tmp/deleted.py', 'assert c.closed\n')
    versions = [old, current, first, second, broken, data, javascript, old_test]
    manifest = tests / 'manifest.json'
    write_json(manifest, {'replay': str(replay), 'submission_state_validated': True, 'tests': [],
                         'source_versions': versions, 'unobserved_source_candidates': [orphan]})
    write_json(tests / 'snapshots/initial.json', {'files': [
        {'kind': 'file', **row} for row in (old, old_test, second, broken, data, javascript)]})
    write_json(tests / 'snapshots/submission.json', {'files': [
        {'kind': 'file', **row} for row in versions if row not in (old, old_test)]})
    actions = [('s1_c0', shlex.join(['python', '-c', 'marker = "中文"\na.send(10)\nb.send(20)\n'])),
               ('s2_c0', "node --eval 'client.send(30)'\n"),
               ('s3_c0', "cd /app && cat > /tmp/deleted.py <<'EOF'\nassert c.closed\nEOF\n"),
               ('s4_c0', 'pytest /app/test_first.py /app/test_second.py'),
               ('s5_c0', 'npx vitest run /app/tests.test.ts')]
    write_json(replay / 'plan.json', {'action_ids': [a for a, _ in actions]})
    inputs = replay / 'inputs'
    inputs.mkdir()
    (inputs / 'instruction.md').write_text('Support `send()` and `closed`. Preserve `type()` and `range()`.')
    (inputs / 'model.patch').write_text('diff --git a/lib.py b/lib.py\n--- a/lib.py\n+++ b/lib.py\n'
                                      '@@ -1,2 +1,2 @@\n-def legacy_only(x):\n-    return x.old\n'
                                      '+def changed(x):\n+    return x.closed\n')
    write_json(inputs / 'trajectory.json', {'steps': [{'reasoning_content': 'REASONING_SENTINEL'}]})
    for identity, command in actions:
        directory = replay / 'runtime/calls' / identity
        directory.mkdir(parents=True)
        (directory / 'command.sh').write_text(command)
        write_json(directory / 'archived_expected.json', {'output': 'historical output without target names'})
        (directory / 'output.bin').write_text('{"duration": 17}\n')
    return manifest


def test_complete_B_workset_and_all_contexts_survive(collected):
    result = targets_from_manifest(collected)
    assert result['records'] == history_records(collected)
    assert all(set(r) == {'id', 'text', 'source'} for r in result['records'])
    assert any('duration' in r['text'] for r in result['records'])
    assert not any('REASONING_SENTINEL' in r['text'] for r in result['records'])
    assert {u['path'] for u in result['units']} >= {'/app/test_first.py', '/app/test_second.py', '/tmp/deleted.py'}


def test_queries_use_issue_and_submitted_patch_not_test_body_symbols(collected):
    result = targets_from_manifest(collected)
    assert {'send', 'closed'} <= set(result['targets'])
    assert not {'old', 'legacy_only', 'resume', 'ready', 'current_state', 'unrelated_call'} & set(result['targets'])
    assert result['missing_patch_sources'] == []
    # Entire authored scopes survive even though their local operations do not
    # expand repository-wide queries.
    assert any('a.unrelated_call()' in read_target_source(u) and u['anchors']
               for u in result['units'] if u['path'] == '/app/test_first.py')


def test_no_selected_or_retained_test_is_required(collected):
    first = targets_from_manifest(collected)
    manifest = read_json(collected)
    manifest.pop('tests')
    write_json(collected, manifest)
    assert first == targets_from_manifest(collected)


def test_frequency_filter_keeps_authored_scopes_and_preserves_all_B_sources(tmp_path):
    repo = ''.join(f'def test_{i}():\n    client.common()\n' for i in range(40))
    new = 'def test_new():\n    client.common()\n    assert special_state\n'
    implementation = 'def changed():\n    client.common()\n'
    materials = []
    for path, text in [('/app/test_repo.py', repo), ('/app/test_new.py', new), ('/app/api.py', implementation)]:
        saved = tmp_path / Path(path).name
        saved.write_text(text)
        materials.append(file_material(path, text, saved))
    command = tmp_path / 'command.sh'
    command.write_text('pytest /app')
    materials.append({'source': str(command), 'kind': 'command', 'action_id': 's1_c0',
                      'expected': {}, 'text': command.read_text()})
    submitted = {m['path']: m['sha256'] for m in materials if m['kind'] == 'file'}
    authored = {('/app/test_new.py', submitted['/app/test_new.py'])}
    patch = 'diff --git a/api.py b/api.py\n--- a/api.py\n+++ b/api.py\n@@ -0,0 +1,2 @@\n+def changed():\n+    client.common()\n'
    result = locate_targets('', patch, materials, submitted, authored)
    assert 'common' not in result['targets']
    assert {u['path'] for u in result['units']} == {'/app/test_new.py'}
    unit, = result['units']
    assert unit['ranges'] == [[0, len(new.encode()) - 1]]
    assert 'special_state' in read_target_source(unit)
    assert {m['source'] for m in materials} == {r['source'] for r in result['records']}


@pytest.mark.parametrize(('path', 'source'), [
    ('/app/test_example.py', 'def test_a():\n    client.send()\ndef test_b():\n    client.send()\n'),
    ('/app/example_test.go', 'package p\nfunc TestA(t *T) { client.send() }\nfunc TestB(t *T) { client.send() }\n'),
    ('/app/example.rs', '#[test] fn a() { client.send(); }\n#[test] fn b() { client.send(); }\n'),
    ('/app/example.test.ts', "it('same',()=>client.send()); it('same',()=>client.send());"),
])
def test_all_authored_tests_across_languages_are_entries(path, source, tmp_path):
    saved = tmp_path / 'source'
    saved.write_text(source)
    material = file_material(path, source, saved)
    result = locate_targets('', '', [material], {path: material['sha256']}, {(path, material['sha256'])})
    roots = [u for u in result['units'] if u['anchors']]
    assert all(covered(u['start'], u['end'], u['ranges']) for u in roots)
    raw, needle = source.encode(), b'client.send()'
    first = raw.index(needle)
    second = raw.index(needle, first + len(needle))
    owners = [min((u for u in roots if covered(a, a + len(needle), u['ranges'])),
                  key=lambda u: u['end'] - u['start']) for a in (first, second)]
    assert len({(u['start'], u['end']) for u in owners}) == 2


def test_full_version_and_decoded_command_positions_read_back(collected):
    result = targets_from_manifest(collected)
    roots = [u for u in result['units'] if u['anchors']]
    versions = {u['source'] for u in roots if u['path'] == '/app/test_first.py'}
    assert len(versions) == 2
    expressions = {read_target_source(u).encode()[a:b] for u in roots for a, b in u['anchors']}
    assert {b'a.send(1)', b'b.send(2)', b'a.send(10)', b'b.send(20)', b'client.send(30)'} <= expressions
    assert any(a > 6000 for u in roots if u['path'] == '/app/test_first.py' for a, b in u['anchors']
               if read_target_source(u).encode()[a:b] == b'a.send(1)')
    written = [u for u in roots if 'write' in u]
    assert any(read_target_source(u) == 'assert c.closed\n' for u in written)


def test_declared_python_encoding_keeps_utf8_coordinates(collected):
    manifest = read_json(collected)
    raw = b'# coding: latin-1\n# caf\xe9\ndef test_encoded():\n    assert client.finished()\n'
    digest = hashlib.sha256(raw).hexdigest()
    path = '/app/test_encoded.py'
    BlobStore(collected.parent / 'blobs').put(raw)
    manifest['source_versions'].append({'path': path, 'sha256': digest})
    write_json(collected, manifest)
    result = targets_from_manifest(collected)
    row = next(u for u in result['units'] if u['path'] == path)
    assert 'café' in read_target_source(row)
    assert covered(row['start'], row['end'], row['ranges'])
    assert row['end'] <= len(read_target_source(row).encode())


@pytest.mark.parametrize('raw', [b'# coding: bad-encoding\ndef test_bad():\n    x.send()\n',
                                 b'# coding: bad-encoding\n# caf\xe9\ndef test_bad():\n    x.send()\n'])
def test_invalid_source_encoding_is_reported_with_original_bytes(collected, raw):
    manifest = read_json(collected)
    digest = hashlib.sha256(raw).hexdigest()
    path = '/app/test_bad.py'
    BlobStore(collected.parent / 'blobs').put(raw)
    manifest['source_versions'].append({'path': path, 'sha256': digest})
    write_json(collected, manifest)
    result = targets_from_manifest(collected)
    error = next(e for e in result['parse_errors'] if e['errors'][0]['kind'] == 'source_encoding')
    assert read_source_bytes(error['source']) == raw
    assert not any(u['path'] == path for u in result['units'])


def test_parse_failures_and_missing_patch_files_keep_material_and_reason(collected):
    manifest = read_json(collected)
    patch = Path(manifest['replay']) / 'inputs/model.patch'
    patch.write_text(patch.read_text() + 'diff --git a/uncollected.py b/uncollected.py\n'
                     '--- a/uncollected.py\n+++ b/uncollected.py\n@@ -1 +1 @@\n-old\n+new\n')
    result = targets_from_manifest(collected)
    assert any(e['source'].endswith('/source_versions/4') for e in result['parse_errors'])
    assert any('def broken(:' in r['text'] for r in result['records'])
    assert result['missing_patch_sources'] == ['uncollected.py']
    assert result['records'] == history_records(collected)


def test_templates_keep_every_unit_origin_and_metrics_agree(collected):
    result = targets_from_manifest(collected)
    indices = [i for group in result['syntax_templates'] for i in group]
    assert sorted(indices) == list(range(len(result['units'])))
    assert result['metrics']['root_units'] == sum(bool(u['anchors']) for u in result['units'])
    assert result['metrics']['anchor_positions'] == sum(len(u['anchors']) for u in result['units'])
    assert result['metrics']['syntax_template_jobs'] == len(result['syntax_templates'])


def test_unexpected_artifact_failure_and_unvalidated_submission_propagate(collected):
    manifest = read_json(collected)
    manifest['submission_state_validated'] = False
    write_json(collected, manifest)
    with pytest.raises(ValueError, match='validated submission state'):
        targets_from_manifest(collected)
    manifest['submission_state_validated'] = True
    write_json(collected, manifest)
    (Path(manifest['replay']) / 'inputs/instruction.md').unlink()
    with pytest.raises(FileNotFoundError):
        targets_from_manifest(collected)


def test_material_order_does_not_change_entries(collected):
    manifest, materials = load_materials(collected)
    inputs = Path(manifest['replay']) / 'inputs'
    submitted = {r['path']: r['sha256'] for r in read_json(collected.parent / 'snapshots/submission.json')['files']}
    issue, patch = (inputs / 'instruction.md').read_text(), (inputs / 'model.patch').read_text()
    first = locate_targets(issue, patch, materials, submitted, set())
    second = locate_targets(issue, patch, list(reversed(materials)), submitted, set())
    assert first['targets'] == second['targets'] and first['units'] == second['units']


def test_CLI_needs_only_manifest_and_new_output(collected, tmp_path):
    output = tmp_path / 'targets.json'
    argv = [sys.executable, '-m', 'eviweave', 'targets', '--manifest', str(collected), '--out', str(output)]
    subprocess.run(argv, cwd=Path(__file__).resolve().parents[1] / 'src', check=True, capture_output=True)
    assert resolve_references(json.loads(output.read_text()),output.parent) == targets_from_manifest(collected)
    rerun = subprocess.run(argv, cwd=Path(__file__).resolve().parents[1] / 'src', capture_output=True)
    assert rerun.returncode != 0


@pytest.mark.parametrize(('command', 'expected'), [
    ("python - <<'PY'\nx.send(1)\nPY\n", 'x.send(1)\n'),
    ("python -c 'x.send(1)'", 'x.send(1)'),
    ("node --input-type=module <<'JS'\nx.send(1)\nJS\n", 'x.send(1)\n'),
    ("npx tsx --eval 'x.send(1)'", 'x.send(1)'),
])
def test_inline_interpreters_and_literal_quoting(command, expected):
    result = inline_sources(command)
    assert result['issues'] == []
    assert [s['text'] for s in result['sources']] == [expected]


def test_shell_dependent_source_is_preserved_as_unresolved():
    command = ('METHOD=send\n' + shlex.quote(sys.executable) + ' - <<PY\nclass Client:\n'
               '    def send(self): print("executed")\nClient().$METHOD()\nPY\n')
    run = subprocess.run(['bash', '-c', command], capture_output=True, text=True, check=True)
    assert run.stdout == 'executed\n'
    result = inline_sources(command)
    assert result['sources'] == []
    assert result['issues'][0]['kind'] == 'inline_shell_expansion'


def test_shell_expansion_depends_on_actual_argument_quoting():
    expanded = inline_sources('python -c "print(\'$METHOD\')"')
    literal = inline_sources("python -c 'print(\"$METHOD\")'")
    attached_expanded = inline_sources('python -c"print(\'$METHOD\')"')
    attached_literal = inline_sources("python -c'print(1)'")
    quoted = inline_sources("python - <<'PY'\nprint('$METHOD')\nPY\n")
    assert not expanded['sources'] and expanded['issues'][0]['kind'] == 'inline_shell_expansion'
    assert literal['sources'][0]['text'] == 'print("$METHOD")' and not literal['issues']
    assert not attached_expanded['sources'] and attached_expanded['issues'][0]['kind'] == 'inline_shell_expansion'
    assert attached_literal['sources'][0]['text'] == 'print(1)' and not attached_literal['issues']
    assert quoted['sources'][0]['text'] == "print('$METHOD')\n" and not quoted['issues']


@pytest.mark.parametrize('command', [
    "python -m package <<'DATA'\nx.send(1)\nDATA\n",
    "python worker.py <<'DATA'\nx.send(1)\nDATA\n",
    "node worker.js <<'DATA'\nx.send(1)\nDATA\n",
])
def test_script_stdin_is_data_not_interpreter_source(command):
    assert inline_sources(command)['sources'] == []
