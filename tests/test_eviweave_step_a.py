"""Real local observations of synthetic repositories; no subject corpus runs."""
import base64
import hashlib
import json
from pathlib import Path
import shlex
import subprocess
import sys
from types import SimpleNamespace

import pytest

from eviweave import snapshot_runner
from eviweave.invocations import commands, in_scope, named_results
from eviweave.collection import ReplayTestCollector, read_source
from eviweave.test_units import discover


def git(root, *args):
    return subprocess.run(['git', '-C', str(root), *args], capture_output=True, check=True).stdout


@pytest.fixture
def repository(tmp_path):
    root = tmp_path / 'repo'
    root.mkdir()
    git(root, 'init', '-q')
    (root / 'base.py').write_text('VALUE = 1\n')
    git(root, 'add', '.')
    git(root, '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid', 'commit', '-qm', 'base')
    return root


class LocalObserver:
    """Executes only our standard-library observer, with /app mapped to a fixture."""
    def __init__(self, repository, output):
        self.repository, self.output = repository, output

    def control(self, argv, *, input_bytes, **kwargs):
        request = json.loads(input_bytes)
        request['root'] = str(self.repository)
        request['extra_paths'] = [p.replace('/app/', str(self.repository) + '/', 1) for p in request['extra_paths']]
        process = subprocess.run([sys.executable, '-I', '-c', argv[-1]], input=json.dumps(request).encode(), capture_output=True, check=True)
        data = json.loads(process.stdout)
        for row in data['files']:
            row['path'] = row['path'].replace(str(self.repository), '/app', 1)
        return SimpleNamespace(returncode=0, stdout=json.dumps(data).encode(), stderr=b'')


def action(identifier, command, output=''):
    return {'id': identifier, 'command': command, 'expected': {'returncode': 0, 'output': output}, 'function': 'bash'}


def record(collector, runtime, item, run=None, output=''):
    collector.before_action(runtime, item)
    if run:
        run()
    directory = runtime.output / 'calls' / item['id']
    directory.mkdir(parents=True)
    (directory / 'output.bin').write_text(output)
    collector.after_action(runtime, item, {'returncode': 0, 'timed_out': False})


def finish(collector, runtime):
    collector.capture_submission(runtime)
    collector.finish({'image_id': 'sha256:' + 'a' * 64, 'head': 'b' * 40},
                     {'matched': True, 'submission_state_status': 'matched', 'submitted_commit_tree_matches': True,
                      'working_tree_matches_submitted_commit': True, 'index_tree_matches_submitted_commit': True})
    return json.loads((collector.out / 'manifest.json').read_text())


def test_observer_preserves_git_and_does_not_import_tests(repository):
    test = repository / 'tests/test_x.py'
    test.parent.mkdir()
    test.write_text('raise RuntimeError("MUST NOT IMPORT")\ndef test_x(): pass\n')
    (repository / 'tests/data.bin').write_bytes(b'\xff\x00fixture')
    (repository / '.env').write_text('secret must not be collected')
    before = git(repository, 'status', '--porcelain=v1')
    result = snapshot_runner.collect({'root': str(repository)})
    assert git(repository, 'status', '--porcelain=v1') == before
    assert not any(Path(row['path']).name == '.env' for row in result['files'])
    for row in result['files']:
        assert hashlib.sha256(base64.b64decode(result['blobs'][row['sha256']])).hexdigest() == row['sha256']
    assert discover('/app/tests/test_x.py', test.read_bytes())['units'][0]['name'] == 'test_x'
    again = snapshot_runner.collect({'root': str(repository), 'known_blobs': list(result['blobs'])})
    assert again['blobs'] == {} and again['files'] == result['files']


@pytest.mark.parametrize('path,source,names', [
    ('tests/test_x.py', 'import pytest\n@pytest.mark.parametrize("x", [1, 2])\ndef test_value(x, fixture): pass\n', ['test_value']),
    ('tests/test_x.py', 'from unittest import TestCase\nclass Checks(TestCase):\n def setUp(self): pass\n def test_x(self): pass\n', ['Checks::test_x']),
    ('x_test.go', 'package x\nimport "testing"\nfunc TestMain(m *testing.M) {}\nfunc TestX(t *testing.T) {}', ['TestX']),
    ('x.test.ts', "describe('outer',()=>{beforeEach(()=>{}); test.each([1,2])('n=%s', (x)=>{}); it('two',()=>{});});", ['outer > n=%s', 'outer > two']),
    ('src/lib.rs', '#[cfg(test)] mod tests { #[test] fn one() {} #[tokio::test] async fn two() {} }', ['tests::one', 'tests::two']),
    ('check.py', 'assert 2 + 2 == 4\n', ['<script>']),
])
def test_function_and_parameter_definitions_across_languages(path, source, names):
    parsed = discover('/app/' + path, source.encode())
    assert parsed['status'] == 'parsed'
    assert [u['name'] for u in parsed['units']] == names
    if 'parametrize' in source:
        unit = parsed['units'][0]
        assert source.splitlines()[unit['first_line'] - 1].startswith('@pytest.mark.parametrize')


def test_shell_scope_cwd_pipeline_and_heredoc_are_preserved():
    raw = "cd /app/sub && python -m pytest tests/test_x.py::test_x -vv 2>&1 | tail -20"
    found = commands([action('s1_c0', raw)])
    row = found['invocations'][0]
    assert row['working_directory'] == '/app/sub'
    assert row['framework'] == 'pytest'
    assert row['shell_command'] == raw and row['signal']['lexical_tokens'][-1] == '-vv'
    assert in_scope({'path': '/app/sub/tests/test_x.py', 'name': 'test_x', 'framework': 'pytest_or_unittest'}, row)
    assert not in_scope({'path': '/app/sub/tests/test_x.py', 'name': 'test_other', 'framework': 'pytest_or_unittest'}, row)
    rows = commands([action('s2_c0', "cat >tests/test_x.py <<'PY'\nprint('pytest fake.py')\nPY\n")])
    assert not rows['invocations'] and '/app/tests/test_x.py' in rows['extra_paths']


def test_shell_expanded_inline_write_does_not_claim_literal_file_contents():
    item = action('s1_c0', 'python -c"from pathlib import Path; Path(\'/app/test_x.py\').write_text(\'$CODE\')"')
    rows = commands([item])
    assert '/app/test_x.py' in rows['extra_paths']
    assert rows['source_literals'] == []


def test_attached_inline_argument_is_recognized_as_script_invocation():
    item = action('s1_c0', "python -c'print(1)'")
    invocation, = commands([item])['invocations']
    assert invocation['signal']['kind'] == 'inline_executable_script'


def test_unquoted_heredoc_preserves_backslashes_unaffected_by_shell(repository):
    command = 'cat >test_x.py <<PY\ns = "line\\n"\nPY\n'
    subprocess.run(['bash', '-c', command], cwd=repository, check=True)
    rows = commands([action('s1_c0', command)])
    assert rows['source_literals'][0]['content'] == (repository / 'test_x.py').read_text()


def test_suite_pass_is_not_individual_execution_and_skip_is_retained(repository, tmp_path):
    test = repository / 'tests/test_x.py'
    test.parent.mkdir()
    test.write_text('def test_one(): pass\ndef test_two(): pass\n')
    actions = [action('s1_c0', 'pytest tests -q', '2 passed in 0.1s'), action('s2_c0', 'pytest tests -vv')]
    collector = ReplayTestCollector(tmp_path / 'collection', actions)
    runtime = LocalObserver(repository, tmp_path / 'runtime')
    collector.start(runtime)
    record(collector, runtime, actions[0], output='2 passed in 0.1s')
    record(collector, runtime, actions[1], output='tests/test_x.py::test_two SKIPPED (reason)\n')
    manifest = finish(collector, runtime)
    assert len(manifest['tests']) == 2
    assert all(u['execution_status'] == 'unconfirmed' for u in manifest['tests'])
    quiet = next(u for u in manifest['tests'] if u['name'] == 'test_one')
    skipped = next(u for u in manifest['tests'] if u['name'] == 'test_two')
    assert quiet['historical_associations'] == []
    assert skipped['historical_associations'][0]['replay_named_reports'][0]['status'] == 'skipped'


def test_named_parameter_results_final_edits_and_deleted_tests(repository, tmp_path):
    tests = repository / 'tests'
    tests.mkdir()
    first = b'def test_keep(): assert True\n'
    second = b'def test_keep(): assert False\n'
    (tests / 'test_keep.py').write_bytes(first)
    (tests / 'test_gone.py').write_text('def test_gone(): pass\n')
    actions = [action('s1_c0', 'pytest tests -vv'), action('s2_c0', 'edit tests and remove old one')]
    collector = ReplayTestCollector(tmp_path / 'collection', actions)
    runtime = LocalObserver(repository, tmp_path / 'runtime')
    collector.start(runtime)
    record(collector, runtime, actions[0], output='tests/test_keep.py::test_keep PASSED\ntests/test_gone.py::test_gone PASSED\n')
    def change():
        (tests / 'test_keep.py').write_bytes(second)
        (tests / 'test_gone.py').unlink()
    record(collector, runtime, actions[1], run=change)
    manifest = finish(collector, runtime)
    retained = [u for u in manifest['tests'] if u['retained_at_submission']]
    assert len(retained) == 1
    current = retained[0]
    assert current['execution_status'] == 'unconfirmed'
    assert current['historical_associations'] == []
    old = [u for u in manifest['tests'] if u['name'] == 'test_gone'][0]
    assert not old['retained_at_submission'] and old['execution_status'] == 'named_report_observed'
    path = collector.out / 'manifest.json'
    assert read_source(path, '/app/tests/test_keep.py') == second
    assert read_source(path, '/app/tests/test_keep.py', sha256=hashlib.sha256(first).hexdigest()) == first
    with pytest.raises(KeyError):
        read_source(path, '/app/tests/test_gone.py')


def test_write_and_test_in_one_action_does_not_claim_exact_run_version(repository, tmp_path):
    (repository / 'tests').mkdir()
    item = action('s1_c0', "cat >tests/test_x.py <<'PY'\ndef test_x(): pass\nPY\npytest tests -vv")
    collector = ReplayTestCollector(tmp_path / 'collection', [item])
    runtime = LocalObserver(repository, tmp_path / 'runtime')
    collector.start(runtime)
    record(collector, runtime, item, run=lambda: (repository / 'tests/test_x.py').write_text('def test_x(): pass\n'),
           output='tests/test_x.py::test_x PASSED\n')
    unit = finish(collector, runtime)['tests'][0]
    assert unit['execution_status'] == 'unconfirmed'
    assert unit['historical_associations'][0]['source_binding'] == 'version_within_command_unresolved'


def test_two_runner_outputs_do_not_fabricate_a_unique_execution_binding(repository, tmp_path):
    (repository / 'test_x.py').write_text('def test_x(): pass\n')
    item = action('s1_c0', 'pytest test_x.py -vv; pytest test_x.py -q')
    collector = ReplayTestCollector(tmp_path / 'collection', [item])
    runtime = LocalObserver(repository, tmp_path / 'runtime')
    collector.start(runtime)
    record(collector, runtime, item, output='test_x.py::test_x PASSED\n')
    assert finish(collector, runtime)['tests'][0]['execution_status'] == 'unconfirmed'


def test_actual_pytest_output_is_linked_to_parameter_instances(repository, tmp_path):
    (repository / 'test_x.py').write_text('import pytest\n@pytest.mark.parametrize("x", [1,2])\ndef test_x(x): assert x > 0\n')
    argv = [sys.executable, '-m', 'pytest', '-vv', 'test_x.py']
    item = action('s1_c0', shlex.join(argv))
    collector = ReplayTestCollector(tmp_path / 'collection', [item])
    runtime = LocalObserver(repository, tmp_path / 'runtime')
    collector.start(runtime)
    collector.before_action(runtime, item)
    result = subprocess.run(argv, cwd=repository, capture_output=True, check=True)
    directory = runtime.output / 'calls' / item['id']
    directory.mkdir(parents=True)
    (directory / 'output.bin').write_bytes(result.stdout)
    collector.after_action(runtime, item, {'returncode': 0, 'timed_out': False})
    unit = finish(collector, runtime)['tests'][0]
    assert unit['execution_status'] == 'named_report_observed'
    assert len(unit['historical_associations'][0]['replay_named_reports']) == 2


def test_same_line_same_name_jest_reports_are_not_assigned_to_either_test(repository, tmp_path):
    (repository / 'same.test.js').write_text("it('same',()=>first());it('same',()=>second());")
    item = action('s1_c0', 'npx jest same.test.js --json')
    collector = ReplayTestCollector(tmp_path / 'collection', [item])
    runtime = LocalObserver(repository, tmp_path / 'runtime')
    collector.start(runtime)
    report = json.dumps({'testResults': [{'name': '/app/same.test.js', 'assertionResults': [
        {'title': 'same', 'ancestorTitles': [], 'status': 'passed'}]}]})
    record(collector, runtime, item, output=report)
    tests = finish(collector, runtime)['tests']
    assert len(tests) == 2 and len({unit['id'] for unit in tests}) == 2
    assert all(unit['execution_status'] == 'unconfirmed' for unit in tests)
    assert all(unit['historical_associations'][0]['ambiguous_named_reports']['replay'][0]['name'] == 'same'
               for unit in tests)


def test_go_rust_reports_retain_names_and_skips():
    assert named_results('ok pkg 0.01s\n', 'go') == []
    assert named_results('--- PASS: TestX/sub (0.00s)\n', 'go')[0]['name'] == 'TestX/sub'
    assert named_results('test tests::one ... ignored\n', 'rust')[0]['status'] == 'skipped'
    assert named_results('tests/test_x.py::test_x[a b] PASSED [100%]\n', 'pytest')[0]['name'].endswith('[a b]')


def test_cached_named_go_output_does_not_confirm_execution(repository, tmp_path):
    (repository / 'x_test.go').write_text('package x\nimport "testing"\nfunc TestX(t *testing.T) {}\n')
    item = action('s1_c0', 'go test . -v')
    collector = ReplayTestCollector(tmp_path / 'collection', [item])
    runtime = LocalObserver(repository, tmp_path / 'runtime')
    collector.start(runtime)
    record(collector, runtime, item, output='--- PASS: TestX (0.00s)\nok example/pkg (cached)\n')
    unit = finish(collector, runtime)['tests'][0]
    assert unit['execution_status'] == 'unconfirmed'
    assert unit['historical_associations'][0]['execution_notices']


def test_deleted_within_one_action_preserves_literal_without_claiming_observed_bytes(repository, tmp_path):
    raw = 'def test_x(): pass\n'
    item = action('s1_c0', "cat >test_x.py <<'PY'\n" + raw + 'PY\npytest test_x.py -vv\nrm test_x.py')
    collector = ReplayTestCollector(tmp_path / 'collection', [item])
    runtime = LocalObserver(repository, tmp_path / 'runtime')
    collector.start(runtime)
    record(collector, runtime, item, output='test_x.py::test_x PASSED\n')
    manifest = finish(collector, runtime)
    assert not manifest['tests']
    candidate = manifest['unobserved_source_candidates'][0]
    assert candidate['action_id'] == item['id']
    assert read_source(collector.out / 'manifest.json', '/app/test_x.py', sha256=candidate['sha256']) == raw.encode()


def test_equal_endpoints_with_explicit_source_edits_are_unconfirmed(repository, tmp_path):
    (repository / 'test_x.py').write_text('def test_x(): pass\n')
    item = action('s1_c0', 'cp alternate.py test_x.py; pytest test_x.py -vv; cp saved.py test_x.py')
    collector = ReplayTestCollector(tmp_path / 'collection', [item])
    runtime = LocalObserver(repository, tmp_path / 'runtime')
    collector.start(runtime)
    record(collector, runtime, item, output='test_x.py::test_x PASSED\n')
    unit = finish(collector, runtime)['tests'][0]
    assert unit['execution_status'] == 'unconfirmed'
    event = json.loads((collector.out / 'executions/s1_c0.json').read_text())
    snapshot = json.loads((collector.out / 'snapshots' / (event['before_snapshot'] + '.json')).read_text())
    source = next(r for r in snapshot['files'] if r['path'] == unit['path'])
    assert source['sha256'] == unit['source_sha256']


def test_scope_exclusion_and_keyword_values_are_not_positive_file_selectors():
    row = commands([action('s1_c0', 'pytest --ignore tests/slow.py -k "foo/bar"')])['invocations'][0]
    assert in_scope({'path': '/app/tests/test_fast.py', 'name': 'test_fast', 'framework': 'pytest_or_unittest'}, row)


def test_cargo_and_package_manager_test_subcommands_do_not_exclude_suite_files():
    cargo = commands([action('s1_c0', 'cargo test -p project --lib')])['invocations'][0]
    rust = {'path': '/app/crates/project/src/lib.rs', 'name': 'tests::one', 'framework': 'rust'}
    assert in_scope(rust, cargo)
    pnpm = commands([action('s2_c0', 'pnpm --filter @project/core test run tests/state.test.ts')])['invocations'][0]
    javascript = {'path': '/app/packages/core/tests/state.test.ts', 'name': 'state', 'framework': 'javascript'}
    assert in_scope(javascript, pnpm)


@pytest.mark.parametrize('command', [
    'pnpm --filter=@project/core test run tests/state.test.ts',
    'pnpm --filter @project/core exec vitest run tests/state.test.ts',
    'pnpm -F @project/core exec vitest run tests/state.test.ts',
    'cd packages/other && pnpm --filter @project/core test run tests/state.test.ts',
])
def test_filtered_pnpm_exec_keeps_possible_package_test_scope(command):
    invocation = commands([action('s1_c0', command)])['invocations'][0]
    unit = {'path': '/app/packages/core/tests/state.test.ts', 'name': 'state', 'framework': 'javascript'}
    assert in_scope(unit, invocation)


def test_cargo_target_and_npm_script_names_are_not_directory_paths():
    cargo = commands([action('s1_c0', 'cargo test --offline --test spec')])['invocations'][0]
    assert in_scope({'path': '/app/tests/spec.rs', 'name': 'case', 'framework': 'rust'}, cargo)
    npm = commands([action('s2_c0', 'npm run tests')])['invocations'][0]
    assert in_scope({'path': '/app/src/state.test.js', 'name': 'case', 'framework': 'javascript'}, npm)


def test_invalid_source_is_preserved_with_its_parse_error(repository, tmp_path):
    raw = b'def test_broken(:\n    pass\n'
    (repository / 'test_broken.py').write_bytes(raw)
    collector = ReplayTestCollector(tmp_path / 'collection', [])
    runtime = LocalObserver(repository, tmp_path / 'runtime')
    collector.start(runtime)
    manifest = finish(collector, runtime)
    assert not manifest['tests'] and len(manifest['parse_errors']) == 1
    error = manifest['parse_errors'][0]
    assert error['path'] == '/app/test_broken.py' and error['reason']
    assert read_source(collector.out / 'manifest.json', error['path']) == raw


def test_greater_than_in_a_quoted_search_pattern_is_not_a_file_write():
    item = action('s81_c0', '''cd /app && grep -n "'|>'\\||>>" test/features/operators.ts''')
    found = commands([item])
    assert found['source_mutations'] == []
