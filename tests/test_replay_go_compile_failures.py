"""An offline supplement replays whole failed groups, without changing history."""
from pathlib import Path
import shutil
import subprocess
from types import SimpleNamespace

import pytest

from relation_search.checkpoint import digest, read, seal, write
from scripts.execute_relation_search import emit_batch, run
from scripts.replay_go_compile_failures import execute, plan
from test_go_compilation_isolation import prepared


@pytest.mark.skipif(shutil.which('go') is None, reason='Local Go toolchain unavailable')
def test_plan_then_replay_unchanged_compile_blocked_group_preserves_original(tmp_path, monkeypatch):
    monkeypatch.setenv('GOPROXY', 'off')
    monkeypatch.setenv('GOTOOLCHAIN', 'local')
    fixture = tmp_path/'fixture'
    fixture.mkdir()
    source, repository, dependencies = prepared(fixture)
    patch = tmp_path/'candidate.patch'
    patch.write_text('')
    registry = tmp_path/'registry.json'
    write(registry, [dict(id='toy', image='toy-image', language='go', base_commit='toy-base',
                         candidate_patch=str(patch))])
    subprocess.run(['go', 'test', '-c', '-o', str(tmp_path/'warm.test'), './pkg'],
                   cwd=repository, check=True, capture_output=True, timeout=120)
    calls = []

    def local_replay(case, command, *, mounts, timeout, output, registry):
        from scripts.relational_phase_runner import execute_plan
        root = tmp_path/('replay_'+str(len(calls)))
        calls.append(root)
        shutil.copytree(repository, root)
        output.mkdir(parents=True)
        for mount in mounts:
            target = root/mount['target']
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(mount['source'], target)
        write(output/'manifest.json', dict(candidate_patch_sha256=digest(patch), image='toy-image',
                                          expected_base_commit='toy-base'))
        execute_plan(read(root/'.relational_phase_inputs/plan.json'), repository=root, logs=output)
        result = dict(returncode=0, output=str(output))
        write(output/'execution.json', result)
        return result

    monkeypatch.setattr('scripts.run_relational_gap_case.run_case', local_replay)
    campaign = tmp_path/'original_campaign'
    folder = campaign/'toy/round_000'
    emit_batch(SimpleNamespace(input=source, output=folder/'emitted', group_size=16, timeout=30,
                               dependency_packages_root=dependencies))
    run(SimpleNamespace(input=folder/'emitted', output=folder/'executed', workers=1, registry=registry))
    original_sha = {str(path): digest(path) for path in campaign.rglob('*') if path.is_file()}
    selected = plan(campaign, registry, dependencies)
    assert selected == plan(campaign, registry, dependencies)
    assert len(selected['groups']) == 1 and selected['candidates'] == 2
    assert selected['groups'][0]['candidate_ids'] == ['invalid', 'detects']
    assert selected['groups'][0]['compile_error_packages'] == ['./pkg']
    plan_path = tmp_path/'supplement_plan.json'
    write(plan_path, selected)
    # A source change is rejected before any new transport or output is made.
    patch.write_text('changed')
    with pytest.raises(ValueError, match='Frozen source changed'):
        execute(plan_path, tmp_path/'new_output', workers=1)
    assert len(calls) == 1 and not (tmp_path/'new_output').exists()
    patch.write_text('')
    with pytest.raises(ValueError, match='outside the original campaign'):
        execute(plan_path, campaign/'supplement')
    output = tmp_path/'supplement'
    result = execute(plan_path, output, workers=1)
    assert result['groups'] == 1 and result['candidates'] == 2
    assert result['provider_calls'] == 0
    assert result['replay_invocations'] == 2 and result['compile_commands'] == 4
    summary, = read(output/'summary.json')
    assert summary['candidate_statuses']['detects']['status'] == 'fail'
    assert summary['candidate_statuses']['detects']['isolation'] == 'fail'
    assert summary['candidate_statuses']['invalid']['status'] == 'error'
    assert summary['candidate_statuses']['invalid']['isolation'] == 'not_run'
    assert all(row['status'] == 'pass' for row in summary['controls'])
    entry = selected['groups'][0]
    copied = read(output/entry['id']/'prepared/candidates.json')['candidates']
    originals = {row['id']: row for row in read(Path(entry['raw_candidates']))}
    assert copied == [originals[key] for key in entry['candidate_ids']]
    assert {str(path): digest(path) for path in campaign.rglob('*') if path.is_file()} == original_sha
    assert execute(plan_path, output, workers=1)['resumed']
    assert len(calls) == 3
    # Incomplete rounds are recorded as skipped, never promoted to failures.
    write(campaign/'toy/round_001/executed/runs.json', [])
    refreshed = plan(campaign, registry, dependencies)
    assert len(refreshed['groups']) == 1
    assert refreshed['skipped'][0]['reason'] == 'execution_not_sealed'


@pytest.mark.parametrize('kind', ['singleton', 'non_go', 'compiled'])
def test_only_sealed_multi_candidate_go_compile_failures_are_selected(tmp_path, kind):
    campaign = tmp_path/'campaign'
    emitted = campaign/'toy/round_000/emitted'
    execution = emitted.parent/'executed'
    manifest = emitted/'group_000/manifest.json'
    generated = dict(role='generated')
    if kind != 'non_go':
        generated['isolation'] = dict(kind='go_test_process', summary_path='go.runner.json')
    write(manifest, dict(candidate_ids=['one'] if kind == 'singleton' else ['one', 'two'], phases=[generated]))
    seal(emitted, {})
    write(execution/'stage.json', {})
    write(execution/'runs.json', [dict(role='generated', manifest=str(manifest),
        execution_context=dict(context_file=str(execution/'group_000/generated/context.json')))])
    write(execution/'group_000/generated/go.runner.json', dict(packages=[dict(status='compiled')]))
    seal(execution, {})
    registry = tmp_path/'registry.json'
    write(registry, [])
    result = plan(campaign, registry, tmp_path/'unused_dependencies')
    assert result['groups'] == [] and result['candidates'] == 0
