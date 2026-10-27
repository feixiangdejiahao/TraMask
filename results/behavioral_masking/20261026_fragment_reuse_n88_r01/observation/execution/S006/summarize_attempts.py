"""Record the failed full-file harness and the unchanged named-unit matrix."""
from pathlib import Path
import hashlib
import json
import re

HERE = Path(__file__).parent
RUN = Path(__file__).resolve().parents[3]
summaries = []
for attempt in ('attempt_001', 'attempt_003_named_unit'):
    directory = HERE / attempt
    manifest = json.loads((directory / 'manifest.json').read_text())
    rows = []
    for planned in manifest['plans']:
        path = Path(planned['out']) / 'result.json'
        result = json.loads(path.read_text())
        plan = json.loads(Path(planned['plan']['path']).read_text())
        assert result['status'] == 'completed' and result['target_executed'] is True
        execution = result['execution']
        assert not any(execution[k] for k in ('timed_out', 'transport_error', 'execution_error'))
        text = re.sub(r'\x1b\[[0-9;]*m', '', execution['stdout'] + execution['stderr'])
        reference_file_error = attempt == 'attempt_001' and planned['implementation'] == 'reference'
        variant = planned['variant']
        expected_failure = variant == 'default_only' or (variant == 'default_and_two_services' and planned['implementation'] == 'delivered')
        if reference_file_error:
            outcome = 'TYPECHECK_ERROR'
            reached = False
            assert 'Test suite failed to run' in text and 'Tests:       0 total' in text
            assert 'TS2322' in text and 'TS2345' in text
            evidence = '11 unrelated named-test type errors; zero tests executed'
        else:
            outcome = 'FAIL' if expected_failure else 'PASS'
            reached = True
            marker = '✕' if expected_failure else '✓'
            assert f'{marker} {manifest["selected_test"]}' in text
            test_totals = next(line for line in text.splitlines() if line.startswith('Tests:'))
            assert f'1 {"failed" if expected_failure else "passed"}' in test_totals
            if expected_failure:
                if planned['implementation'] == 'delivered':
                    assert 'Expected: 2\n    Received: 1' in text
                    evidence = 'maxActive1 contradicts preserved expected2'
                else:
                    assert 'Expected: <= 2\n    Received:    3' in text
                    evidence = 'Correct default parallelism reaches3; old finite-cap assertion rejects this singleton edit'
            else:
                evidence = 'Complete selected named test passes both original maxActive assertions'
        assert execution['returncode'] == (0 if outcome == 'PASS' else 1)
        snaps = result['production_snapshots']
        before, after = [json.loads(snaps[k]['stdout']) for k in ('before_build', 'final')]
        assert before == after
        assert {p['path'] for p in before['paths']} == set(plan['production_paths'])
        head = plan['base_commit'] if plan['implementation'] == 'reference' else plan['checkpoint']['head']
        assert result['final_head']['stdout'].strip() == head
        allowed = set(plan['production_paths']) | {f['destination'].removeprefix('/app/') for f in plan['files']}
        assert not [line for line in result['final_status']['stdout'].splitlines()
                    if line[:2] != '??' and line[3:] not in allowed]
        rows.append({**{k:planned[k] for k in ('id','variant','implementation','repeat')},
                     'outcome': outcome, 'actual_named_test_reached': reached,
                     'evidence': evidence, 'monitored_patch_paths': len(before['paths']),
                     'monitored_sources_unchanged': True,
                     'result': {'path': str(path.relative_to(RUN)), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()},
                     'stdout_sha256': execution['stdout_sha256'], 'stderr_sha256': execution['stderr_sha256']})
    summary = {'case_id': 'S006', 'stage': 'informed_observation', 'counts_as_blind_result': False,
               'attempt': attempt, 'scope': manifest['scope'], 'repeats': 2, 'rows': rows,
               'whole_original_file_reference_compatible': False,
               'validated_detection': attempt == 'attempt_003_named_unit'}
    with (directory / 'matrix_summary.json').open('x') as stream:
        json.dump(summary, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
    summaries.append({'attempt': attempt, 'executions': len(rows), 'validated_detection': summary['validated_detection']})

with (HERE / 'execution_summary.json').open('x') as stream:
    json.dump({'case_id': 'S006', 'stage': 'informed_observation', 'counts_as_blind_result': False,
               'attempts': summaries, 'preparation_only_failure': 'attempt_002_named_unit/preparation_error.json',
               'named_unit_matrix': {
                   'original': 'P PASS / R PASS', 'default_only': 'P FAIL / R FAIL',
                   'two_services_only': 'P PASS / R PASS', 'default_and_two_services': 'P FAIL / R PASS'},
               'meaning': 'Both setup changes are needed among the tested subsets to make the unchanged max2 decision valid and discriminating.',
               'scope_timing': 'Complete named test selected before execution; extracted verbatim after reference type errors in other file tests. First attempt retained.',
               'global_minimality': 'not_established; changing the oracle permits other assemblies'}, stream, ensure_ascii=False, indent=2)
    stream.write('\n')
print(json.dumps(summaries))
