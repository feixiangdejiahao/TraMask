"""Real Go phases with only the Docker transport replaced by a local copy."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
from types import SimpleNamespace

import pytest

from anchor_retrieval.syntax import Source
from relational_gap.frontend import extract_frontend, to_emitter_corpus
from relation_search.checkpoint import read, write
from scripts.execute_relation_search import emit_batch, go_isolation_harness, run


CODE = '''package toy
import ("testing"; "time")
func TestSeed(t *testing.T) {
    hang := false
    if hang { for { time.Sleep(time.Second) } }
    if 1 != 1 { t.Fatal("actual assertion failure") }
}
'''


@pytest.mark.skipif(shutil.which('go') is None, reason='Local Go toolchain unavailable')
def test_same_group_hang_does_not_poison_completed_control_pass_or_failure(tmp_path, monkeypatch):
    monkeypatch.setenv('GOPROXY', 'off')
    monkeypatch.setenv('GOTOOLCHAIN', 'local')
    repository = tmp_path/'repository'
    (repository/'pkg').mkdir(parents=True)
    (repository/'go.mod').write_text('module example.test/integration\n\ngo 1.18\n')
    (repository/'pkg/seed_test.go').write_text(CODE)
    subprocess.run(['go', 'test', '-c', '-o', str(tmp_path/'warm.test'), './pkg'],
                   cwd=repository, check=True, capture_output=True, timeout=120)
    frontend = extract_frontend([Source('pkg/seed_test.go', CODE, 'go')])
    corpus = to_emitter_corpus(frontend)
    base = next(iter(corpus['tests']))
    candidates = []
    for identifier, before, after in [('a_hang', 'false', 'true'),
                                      ('b_pass', '1 != 1', '1 != 1'),
                                      ('c_failure', '1 != 1', '1 != 2')]:
        start = CODE.index(before)
        candidates.append(dict(id=identifier, base_test_id=base, source_test_ids=[], language='go',
                               imports=[], kind='test_fixture', source_provenance={'test': base},
                               edits=[dict(span=dict(path='pkg/seed_test.go', start_byte=start,
                                                     end_byte=start+len(before)), before=before, after=after)]))
    source = tmp_path/'prepared'
    documents = {'case.json': {'id': 'toy', 'language': 'go', 'repository': str(repository), 'image': 'toy-image'},
                 'corpus.json': corpus, 'selection.json': {}, 'candidates.json': {'candidates': candidates}}
    for name, content in documents.items():
        write(source/name, content)
    write(source/'prepare.json', {'files_sha256': {
        name: hashlib.sha256((source/name).read_bytes()).hexdigest() for name in documents}})
    dependencies = tmp_path/'dependencies'
    write(dependencies/'toy.json', {'image': 'toy-image', 'import_package_sources': {}})
    registry = tmp_path/'registry.json'
    write(registry, [])
    calls = []

    def replay(case, command, *, mounts, timeout, output, registry):
        from scripts.relational_phase_runner import execute_plan
        calls.append(command)
        root = tmp_path/('replay_' + str(len(calls)))
        shutil.copytree(repository, root)
        output.mkdir(parents=True)
        for mount in mounts:
            destination = root/mount['target']
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(mount['source'], destination)
        plan = read(root/'.relational_phase_inputs/plan.json')
        assert [phase['role'] for phase in plan['phases']] == ['control', 'generated']
        execute_plan(plan, repository=root, logs=output)
        result = {'returncode': 0, 'output': str(output)}
        write(output/'execution.json', result)
        return result

    monkeypatch.setattr('scripts.run_relational_gap_case.run_case', replay)
    emitted, executed = tmp_path/'emitted', tmp_path/'executed'
    emitted_result = emit_batch(SimpleNamespace(input=source, output=emitted, group_size=16, timeout=12,
                                                dependency_packages_root=dependencies))
    assert emitted_result['artifacts'] == 1
    manifest = read(emitted/'group_000/manifest.json')
    assert all(phase['isolation']['timeout'] == 7 for phase in manifest['phases'])
    assert manifest['phases'][1]['isolation']['selection'] == {
        './pkg': ['TestGC_a_hang', 'TestGC_b_pass', 'TestGC_c_failure']}
    outcome = run(SimpleNamespace(input=emitted, output=executed, registry=registry, workers=1))
    assert outcome['outcomes'][0]['status'] == 'error'
    assert len(calls) == 1
    rows = read(executed/'runs.json')
    control, = [row for row in rows if row['role'] == 'control']
    generated = {row['candidate_id']: row for row in rows if row['role'] == 'generated'}
    assert read(Path(control['result']))['errors'] == []
    assert read(Path(control['result']))['counts']['pass'] == 1
    assert control['test_ids'][0] in generated['b_pass']['control_ids']
    passed = read(Path(generated['b_pass']['result']))
    failed = read(Path(generated['c_failure']['result']))
    hung = read(Path(generated['a_hang']['result']))
    assert passed['status'] == 'pass' and passed['errors'] == []
    assert failed['status'] == 'fail' and failed['errors'] == []
    assert failed['counts']['fail'] == 1
    assert hung['status'] == 'error' and hung['counts']['fail'] == 0 and hung['counts']['pass'] == 0
    assert generated['a_hang']['isolation']['status'] == 'timeout'
    assert read(Path(generated['a_hang']['result']).parent/'result.json')['timed_out']
    generated_binaries = []
    for row in rows:
        result_path = Path(row['result'])
        assert result_path.parent.parent.name == 'isolated'
        assert result_path.parents[2].name == row['role']
        assert Path(row['execution_context']['context_file']) == result_path.parents[2]/'context.json'
        provenance = read(Path(row['isolation']['provenance']))
        assert provenance['raw_evidence']
        assert provenance['source_snapshot'] == row['execution_context']['source_snapshot']
        assert len(provenance['compiled_binaries']) == 1
        if row['role'] == 'generated':
            generated_binaries.append(provenance['compiled_binaries'][0])
        for record in provenance['raw_evidence']:
            assert hashlib.sha256(Path(record['path']).read_bytes()).hexdigest() == record['sha256']
        assert (result_path.parent/'source_process.json').exists()
        assert (result_path.parent/'stdout.txt').read_bytes() == Path(read(result_path.parent/'source_process.json')['stdout']).read_bytes()
    assert all(binary == generated_binaries[0] for binary in generated_binaries)
    group_generated = read(executed/'group_000/generated/normalized.json')
    assert group_generated['errors'] and group_generated['isolation']['counts']['timeout'] == 1
    assert group_generated['counts'] == {'pass': 1, 'fail': 1, 'skip': 0, 'error': 0}
    resumed = run(SimpleNamespace(input=emitted, output=executed, registry=registry, workers=1))
    assert resumed['resumed'] and len(calls) == 1

    # Consume the actual isolated layout, rather than fabricating normalized
    # reports: the group is an execution error, but its two completed generated
    # tests have valid source controls and remain usable search parents.
    from relation_search.feedback import collect
    feedback = collect(executed)
    assert feedback['attempted_candidate_ids'] == ['a_hang', 'b_pass', 'c_failure']
    assert feedback['executed_candidate_ids'] == ['b_pass', 'c_failure']
    assert {row['candidate']['id'] for row in feedback['eligible_parents']} == {'b_pass', 'c_failure'}
    decisions = {row['candidate_id']: row for row in feedback['current_results']}
    assert decisions['a_hang']['executed'] is False
    assert decisions['a_hang']['parent_eligible'] is False
    assert decisions['a_hang']['candidate_outcomes'][0]['report_errors']
    for name in ('b_pass', 'c_failure'):
        assert decisions[name]['parent_eligible'] and decisions[name]['control_and_seed_valid']
        assert decisions[name]['candidate_outcomes'][0]['report_errors'] == []
    counters = feedback['rounds'][0]['counters']
    assert counters['control_pass'] == 1
    assert counters['generated_pass'] == 1 and counters['generated_fail'] == 1
    assert counters['control_error'] == 0 and counters['generated_error'] == 0
    assert counters['executed_test_outcomes'] == counters['reported_test_outcomes'] == 3
    assert set(counters) == {
        *(f'{role}_{status}' for role in ('control', 'generated') for status in ('pass', 'fail', 'skip', 'error')),
        'reported_test_outcomes', 'executed_test_outcomes'}
    phases = [executed/'group_000'/role/'result.json' for role in ('control', 'generated')]
    phase_elapsed = sum(read(path)['elapsed_seconds'] for path in phases)
    individual_elapsed = sum(read(Path(row['result']).parent/'result.json')['elapsed_seconds'] for row in rows)
    assert phase_elapsed > individual_elapsed  # Includes discovery and compilation.
    assert feedback['rounds'][0]['elapsed_test_seconds'] == pytest.approx(phase_elapsed)
    evidence = feedback['rounds'][0]['evidence_sha256']
    assert all(str(path) in evidence for path in phases)
    assert all(str(Path(row['result']).parent/'result.json') in evidence for row in rows)
    assert collect(executed, previous=feedback) == feedback


def test_package_selection_uses_emitted_test_paths_and_exact_names():
    emission = {'files': {'pkg/x_test.go': 'package pkg', 'helpers/h_test.go': 'package helpers'}}
    items = [{'path': 'pkg/x_test.go', 'test_name': 'TestA'},
             {'path': 'helpers/h_test.go', 'test_name': 'TestDonor'}]
    harness = go_isolation_harness(emission, items, 180)
    assert harness['isolation']['selection'] == {'./helpers': ['TestDonor'], './pkg': ['TestA']}
    assert harness['isolation']['timeout'] == 175
    assert '--package ./helpers' in harness['command'] and '--package ./pkg' in harness['command']
    assert '.relational_phase_inputs/go_test_runner.py' in harness['files']
