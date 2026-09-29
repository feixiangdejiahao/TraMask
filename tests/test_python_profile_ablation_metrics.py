import json

from scripts.compare_python_profile_ablation import add_reachability, summarize_case


def test_shared_reports_count_once_and_source_failures_do_not_become_qualified(tmp_path):
    case = tmp_path/'P1'
    folder = case/'round_000'

    def write(path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value))

    candidates = [dict(id='a', operator='executed_parent_extension', runtime_parent_id='parent'),
                  dict(id='b', operator='other'), dict(id='c', operator='other')]
    for relative in ('prepared/candidates.json', 'prepared/source_pool.json', 'semantic/candidates.json'):
        write(folder/relative, {'candidates': candidates})
    write(folder/'feedback.json', dict(current_results=[dict(candidate_id='a', control_and_seed_valid=False)],
        rounds=[dict(new_generated_profiles=4, new_eligible_generated_profiles=0, generated_with_profiles=1)],
        eligible_parents=[], measured_profile_count=4))
    write(folder/'executed/checkpoint.json', {'result': {'wall_seconds': 8}})
    manifest = str(folder/'emitted/group_000/manifest.json')
    runs = []
    for role, data, duration, start in [
        ('control', [('ca', None, 'pass', []), ('cb', None, 'fail', [])], 1, 0),
        ('source_profile', [('seed', 'source_profile_a', 'fail', ['ca'])], 2, 1),
        ('generated', [('ta', 'a', 'fail', ['ca']), ('tb', 'b', 'pass', ['cb']),
                       ('tc', 'c', 'error', ['ca'])], 3, 3),
    ]:
        directory = folder/'executed/group_000'/role
        report = directory/'normalized.json'
        write(report, dict(tests=[dict(id=name, status=status) for name, _, status, _ in data],
            counts={status: sum(row[2] == status for row in data) for status in ('pass', 'fail', 'error', 'skip')}, errors=[]))
        write(directory/'result.json', dict(elapsed_seconds=duration, timed_out=False))
        (directory/'junit.xml').write_text(f'<testsuites><testsuite timestamp="2026-09-29T00:00:0{start}+00:00" time="{duration}" /></testsuites>')
        for name, identifier, _, controls in data:
            runs.append(dict(result=str(report), role=role, manifest=manifest,
                             candidate_id=identifier, test_ids=[name], control_ids=controls))
    write(folder/'executed/runs.json', runs)
    result = summarize_case(case, dict(stopped_reason='round_budget', rounds=[
        dict(round=0, semantic=dict(provider_calls=0, revised_count=0))]))
    assert result['total_test_body_executions'] == 5
    assert result['generated_test_body_executions'] == 2
    assert result['execution_counts']['generated_error'] == 1
    assert result['source_control_qualified_generated_failures'] == 1
    assert result['source_and_seed_qualified_generated_failures'] == 0
    assert result['phase_elapsed_seconds'] == 6
    assert result['execution_stage_wall_seconds'] == 8
    assert result['rounds'][0]['actually_executed_generated_ids'] == ['a', 'b']
    assert result['rounds'][0]['executed_extension_ids'] == ['a']
    diagnostic = {'matching_executions_for_review': [
        dict(case='P1', id='a', reference_id='old_a', complete_signature_matches=True,
             result=str(folder/'executed/group_000/generated/normalized.json')),
        dict(case='P1', id='b', reference_id='old_b', complete_signature_matches=False,
             result=str(folder/'executed/group_000/generated/normalized.json'))]}
    add_reachability(result, diagnostic)
    assert len(result['known_material_execution_matches']) == 1
    witness = result['first_known_material_failure_pending_review']
    assert witness['body_execution_ordinal'] == 4
    assert witness['generated_execution_ordinal'] == 1
    assert witness['seconds_from_first_suite_upper_bound'] == 6
    assert 'fresh failure-cause/control review remains separate' in witness['interpretation']
