"""Check the frozen S085 matrix against named test output and unchanged sources."""
from pathlib import Path
import hashlib
import json
import re

ATTEMPT = Path(__file__).parent / 'attempt_001'
RUN = Path(__file__).resolve().parents[3]
manifest = json.loads((ATTEMPT / 'manifest.json').read_text())
name = manifest['selected_test']
rows = []
for planned in manifest['plans']:
    path = Path(planned['out']) / 'result.json'
    result = json.loads(path.read_text())
    plan = json.loads(Path(planned['plan']['path']).read_text())
    assert result['status'] == 'completed' and result['target_executed'] is True
    execution = result['execution']
    assert not any(execution[k] for k in ('timed_out', 'transport_error', 'execution_error'))
    stdout = re.sub(r'\x1b\[[0-9;]*m', '', execution['stdout'])
    expected_failure = planned['variant'] in {'history_bc', 'derived_threshold_350'} and planned['implementation'] == 'delivered'
    verdict = 'FAIL' if expected_failure else 'PASS'
    marker = '×' if expected_failure else '✓'
    assert f'{marker} test/duration-shard.test.ts > {name}' in stdout
    assert ('Tests  1 failed | 10 skipped (11)' if expected_failure else 'Tests  1 passed | 10 skipped (11)') in stdout
    assert execution['returncode'] == (1 if expected_failure else 0)
    if expected_failure:
        assert "expected [ '1.test.js', '2.test.js' ] to deeply equal [ '1.test.js' ]" in stdout
    snapshots = result['production_snapshots']
    before, after = [json.loads(snapshots[k]['stdout']) for k in ('before_build', 'final')]
    assert before == after
    assert {p['path'] for p in before['paths']} == set(plan['production_paths'])
    expected_head = plan['base_commit'] if plan['implementation'] == 'reference' else plan['checkpoint']['head']
    assert result['final_head']['stdout'].strip() == expected_head
    allowed_changes = set(plan['production_paths']) | {f['destination'].removeprefix('/app/') for f in plan['files']}
    extra_tracked = [line for line in result['final_status']['stdout'].splitlines()
                     if line[:2] != '??' and line[3:] not in allowed_changes]
    assert not extra_tracked
    rows.append({**{k:planned[k] for k in ('id','variant','implementation','repeat')},
                 'test_outcome': verdict, 'target_test_count': 1, 'other_named_tests_skipped': 10,
                 'monitored_patch_paths': len(before['paths']), 'monitored_sources_unchanged': True,
                 'result': {'path': str(path.relative_to(RUN)), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()},
                 'stdout_sha256': execution['stdout_sha256']})

summary = {
    'case_id': 'S085', 'stage': 'informed_observation', 'counts_as_blind_result': False,
    'selected_scope': manifest['scope'], 'repeats': 2, 'rows': rows,
    'findings': {
        'original': 'P PASS / R PASS',
        'history_b_only': 'P PASS / R PASS',
        'history_c_only': 'P PASS / R PASS',
        'history_bc': 'P FAIL / R PASS',
        'derived_threshold_350': 'P FAIL / R PASS',
        'failing_effect': 'Slow file1 shares shard1 with normal file2; original expected sole file1.',
        'historical_transfer': 'Two complete observation records from the executed history snapshot; all test operations and expected arrays retained.',
        'local_necessity': 'Both record substitutions are necessary among the tested subsets for this fixture. They instantiate one duration-distribution condition.',
        'alternative': 'One threshold parameter, set to350 in both calls, also reveals the bug;350 was derived and is not an exact previously executed numeric value.',
        'global_minimality': 'not_established',
    },
}
with (ATTEMPT / 'matrix_summary.json').open('x') as stream:
    json.dump(summary, stream, ensure_ascii=False, indent=2)
    stream.write('\n')
print(json.dumps({'checked_runs': len(rows), 'findings': summary['findings']}, ensure_ascii=False))
