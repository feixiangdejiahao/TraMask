"""Bind named runner results to a retained test on its submitted checkpoint."""
from pathlib import Path

from .artifacts import read_json, read_manifest, write_json
from .execution import patch_paths, run_in_checkpoint
from .invocations import commands, in_scope, named_results, result_matches, result_notices, source_may_change_during_action


def run_selected_test(manifest_path, test_id, command, out, *, workdir='/app', env=None,
                      build_commands=(), timeout=120):
    manifest_path = Path(manifest_path).resolve()
    manifest = read_manifest(manifest_path)
    assert manifest['submission_state_validated'], 'Baseline requires a validated submitted checkpoint'
    retained = [u for u in manifest['tests'] if u['retained_at_submission']]
    unit = next(u for u in retained if u['id'] == test_id)
    discovery = commands([{'id': 'baseline', 'command': command}], default_workdir=workdir)
    invocations = discovery['invocations']
    assert len(invocations) == 1 and in_scope(unit, invocations[0]), 'Select the test with one runner command'
    invocation = invocations[0]
    sources = {unit['path']: unit['source_sha256']}
    submission = read_json(manifest_path.parent / 'snapshots/submission.json')
    sources.update({r['path']: r['sha256'] for r in submission['files'] if r['kind'] == 'file' and (
        r['path'].endswith('/conftest.py') and unit['path'].startswith(str(Path(r['path']).parent) + '/')
        or Path(r['path']).name in {'package.json', 'pyproject.toml', 'pytest.ini', 'setup.cfg',
                                   'go.mod', 'Cargo.toml', 'Makefile', 'tsconfig.json'}
        and unit['path'].startswith(str(Path(r['path']).parent) + '/'))})
    replay = Path(manifest['replay'])
    plan = read_json(replay / 'plan.json')
    patch = replay / plan['inputs']['model.patch']['path']
    paths = sorted(set(sources) | set(patch_paths(patch.read_text())))
    result = run_in_checkpoint(manifest['checkpoint'], command, out, workdir=workdir, env=env,
                               build_commands=build_commands, timeout=timeout, source_paths=paths)
    output = Path(result['execution']['output']).read_text(errors='replace') if result['execution'] else ''
    framework = 'pytest' if unit['framework'] == 'pytest_or_unittest' else unit['framework']
    reports = named_results(output, framework)
    candidates = [u for u in retained if in_scope(u, invocation)]
    matched = [r for r in reports if result_matches(unit, r, invocation['working_directory'])]
    selected = [r for r in matched if sum(result_matches(u, r, invocation['working_directory']) for u in candidates) == 1]
    notices = result_notices(output, framework)
    unchanged = result['sources']['unchanged'] and all(
        result['sources']['before'][p].get('sha256') == sha for p, sha in sources.items())
    version_bound = not source_may_change_during_action(invocation, unit, discovery)
    valid_run = result['status'] == 'completed' and unchanged and version_bound and not notices
    statuses = {r['status'] for r in selected}
    verdict = ('failed' if statuses & {'failed', 'error'} else 'passed' if statuses == {'passed'}
               else 'skipped' if statuses and statuses <= {'skipped', 'pending', 'xfailed', 'xfail'} else 'unconfirmed')
    baseline = {'manifest': str(manifest_path), 'test_id': test_id,
                'test': {'path': unit['path'], 'name': unit['name'], 'sha256': unit['source_sha256']},
                'execution_result': str(Path(out).resolve() / 'result.json'), 'runner_status': result['status'],
                'sources_unchanged': unchanged, 'source_version_bound': version_bound,
                'named_reports': selected, 'ambiguous_named_reports': [r for r in matched if r not in selected],
                'execution_notices': notices, 'test_outcome': verdict if valid_run else 'unconfirmed',
                'test_execution': 'named_report_observed' if valid_run and statuses & {'passed', 'failed', 'xpass'} else 'unconfirmed'}
    write_json(Path(out) / 'baseline.json', baseline)
    return baseline
