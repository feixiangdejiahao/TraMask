"""Compile isolation must protect executable siblings, not hide bad inputs."""
import hashlib
from pathlib import Path
import shutil
import subprocess
from types import SimpleNamespace

import pytest

from anchor_retrieval.syntax import Source
from relational_gap.frontend import extract_frontend, to_emitter_corpus
from relation_search.checkpoint import read, write
from scripts.execute_relation_search import emit_batch, run


GO_TEST = '''package toy
import "testing"
func TestSeed(t *testing.T) {
    got := combine(2, 0)
    if got != 2 { t.Fatalf("wrong sum: %d", got) }
}
'''
GO_SUBJECT = '''package toy
// This incomplete implementation ignores the second operand.
func combine(left, right int) int { return left }
'''


def prepared(tmp_path, language='go'):
    repository = tmp_path/'repository'
    repository.mkdir()
    if language == 'go':
        (repository/'pkg').mkdir()
        (repository/'go.mod').write_text('module example.test/compilation\n\ngo 1.18\n')
        (repository/'pkg/subject.go').write_text(GO_SUBJECT)
        path, code = 'pkg/seed_test.go', GO_TEST
    else:
        path, code = 'test_seed.py', 'def test_seed():\n    assert 2 == 2\n'
    (repository/path).write_text(code)
    corpus = to_emitter_corpus(extract_frontend([Source(path, code, language)]))
    base = next(iter(corpus['tests']))

    def edit(before, after, role='input'):
        start = code.index(before)
        return dict(before=before, after=after, role=role,
                    span=dict(path=path, start_byte=start, end_byte=start+len(before)))

    if language == 'go':
        changes = [('invalid', [edit('combine(2, 0)', 'combine(2)')]),
                   ('detects', [edit('combine(2, 0)', 'combine(2, 3)'),
                                edit('got != 2', 'got != 5', 'semantic_expected')])]
    else:
        changes = [('first', [edit('2 == 2', '2 == 2')]),
                   ('second', [edit('2 == 2', '2 == 3')])]
    candidates = [dict(id=identifier, base_test_id=base, source_test_ids=[], language=language,
                       imports=[], kind='test_fixture', source_provenance={'test': base}, edits=edits)
                  for identifier, edits in changes]
    source = tmp_path/'prepared'
    documents = {'case.json': {'id': 'toy', 'language': language, 'repository': str(repository), 'image': 'toy-image'},
                 'corpus.json': corpus, 'selection.json': {}, 'candidates.json': {'candidates': candidates}}
    for name, value in documents.items():
        write(source/name, value)
    write(source/'prepare.json', {'files_sha256': {
        name: hashlib.sha256((source/name).read_bytes()).hexdigest() for name in documents}})
    dependencies = tmp_path/'dependencies'
    write(dependencies/'toy.json', {'image': 'toy-image', 'import_package_sources': {}})
    return source, repository, dependencies


@pytest.mark.skipif(shutil.which('go') is None, reason='Local Go toolchain unavailable')
def test_invalid_sibling_cannot_prevent_real_go_detection_after_compile_isolation(tmp_path, monkeypatch):
    monkeypatch.setenv('GOPROXY', 'off')
    monkeypatch.setenv('GOTOOLCHAIN', 'local')
    source, repository, dependencies = prepared(tmp_path)
    subprocess.run(['go', 'test', '-c', '-o', str(tmp_path/'warm.test'), './pkg'],
                   cwd=repository, check=True, capture_output=True, timeout=120)
    registry = tmp_path/'registry.json'
    write(registry, [])
    replays = []

    def local_replay(case, command, *, mounts, timeout, output, registry):
        from scripts.relational_phase_runner import execute_plan
        root = tmp_path/('replay_' + str(len(replays)))
        replays.append(root)
        shutil.copytree(repository, root)
        output.mkdir(parents=True)
        for mount in mounts:
            target = root/mount['target']
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(mount['source'], target)
        execute_plan(read(root/'.relational_phase_inputs/plan.json'), repository=root, logs=output)
        result = {'returncode': 0, 'output': str(output)}
        write(output/'execution.json', result)
        return result

    monkeypatch.setattr('scripts.run_relational_gap_case.run_case', local_replay)
    metrics = {}
    for label, isolate in [('shared', False), ('isolated', True)]:
        emitted, executed = tmp_path/label/'emitted', tmp_path/label/'executed'
        arguments = SimpleNamespace(input=source, output=emitted, group_size=16, timeout=30,
                                    dependency_packages_root=dependencies)
        if isolate:
            arguments.isolate_go_compilation = True
        receipt = emit_batch(arguments)
        assert receipt['artifacts'] == (2 if isolate else 1)
        stage = read(emitted/'stage.json')
        assert stage['group_size'] == 16
        assert stage['effective_group_size'] == (1 if isolate else 16)
        assert stage['isolate_go_compilation'] is isolate
        assert read(emitted/'execution_lanes.json')['max_group_size'] == stage['effective_group_size']
        outcome = run(SimpleNamespace(input=emitted, output=executed, registry=registry, workers=1))
        rows = read(executed/'runs.json')
        controls = [row for row in rows if row['role'] == 'control']
        generated = {row['candidate_id']: row for row in rows if row['role'] == 'generated'}
        assert set(generated) == {'invalid', 'detects'}
        assert all(read(Path(row['result']))['status'] == 'pass' for row in controls)
        assert generated['invalid']['isolation']['status'] == 'not_run'
        invalid_result = read(Path(generated['invalid']['result']).parent/'result.json')
        assert invalid_result['isolation_reason'] == 'compile_error'
        assert read(Path(generated['invalid']['result']))['counts']['fail'] == 0
        invalid_provenance = read(Path(generated['invalid']['isolation']['provenance']))
        assert invalid_provenance['compiled_binaries'] == []
        assert any('not enough arguments' in Path(row['path']).read_text(errors='replace')
                   for row in invalid_provenance['raw_evidence'] if row['path'].endswith('build-output.txt'))
        expected_status = 'fail' if isolate else 'error'
        assert read(Path(generated['detects']['result']))['status'] == expected_status
        if isolate:
            valid = read(Path(generated['detects']['result']))
            assert valid['counts']['fail'] == 1 and valid['errors'] == []
            assert generated['detects']['isolation']['status'] == 'fail'
            invalid_manifest = read(Path(generated['invalid']['manifest']))
            valid_manifest = read(Path(generated['detects']['manifest']))
            assert invalid_manifest['candidate_ids'] == ['invalid']
            assert valid_manifest['candidate_ids'] == ['detects']
            assert valid_manifest['compilation_isolation'] == 'one_candidate_source_snapshot'
            assert Path(generated['invalid']['manifest']) != Path(generated['detects']['manifest'])
        else:
            assert generated['detects']['isolation']['status'] == 'not_run'
        from relation_search.feedback import collect
        feedback = collect(executed)
        assert feedback['executed_candidate_ids'] == (['detects'] if isolate else [])
        assert [row['candidate']['id'] for row in feedback['eligible_parents']] == (['detects'] if isolate else [])
        summaries = [read(path) for path in sorted(executed.glob('group_*/*/go.runner.json'))]
        compilations = [package['compilation'] for summary in summaries for package in summary['packages']]
        metrics[label] = dict(artifacts=receipt['artifacts'], replay_invocations=receipt['artifacts'],
                             phases=len(summaries), compile_commands=len(compilations),
                             compilation_seconds=sum(row['elapsed_seconds'] for row in compilations),
                             phase_seconds=sum(read(path)['elapsed_seconds'] for path in executed.glob('group_*/*/result.json')),
                             wall_seconds=outcome['wall_seconds'],
                             executed_candidate_ids=feedback['executed_candidate_ids'],
                             completed_control_count=len(controls))
        # An unchanged policy can resume; changing the compilation boundary
        # cannot silently reuse the prior grouped result.
        assert emit_batch(arguments)['resumed']
        arguments.isolate_go_compilation = not isolate
        with pytest.raises(ValueError, match='Resume inputs or algorithm changed'):
            emit_batch(arguments)
        assert run(SimpleNamespace(input=emitted, output=executed, registry=registry, workers=1))['resumed']
    assert len(replays) == 3
    assert metrics['shared']['compile_commands'] == 2
    assert metrics['isolated']['compile_commands'] == 4
    metrics['transport'] = 'local repository copies replace Docker only; Go compilation and test processes are real'
    write(tmp_path/'compilation_isolation_comparison.json', metrics)


def test_go_option_does_not_split_other_languages(tmp_path):
    source, _, dependencies = prepared(tmp_path, 'python')
    output = tmp_path/'emitted'
    result = emit_batch(SimpleNamespace(input=source, output=output, group_size=16, timeout=30,
                        dependency_packages_root=dependencies, isolate_go_compilation=True))
    assert result['artifacts'] == 1
    assert read(output/'stage.json')['effective_group_size'] == 16
    assert read(output/'execution_lanes.json')['compilation_isolation'] == 'not_applicable'
    assert len(read(output/'group_000/manifest.json')['candidate_ids']) == 2
