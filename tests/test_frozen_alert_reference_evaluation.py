import json

import pytest

from scripts.evaluate_frozen_alert_references import normalize


@pytest.mark.parametrize('control_status,generated_status,failed,passed', [
    ('pass', 'fail', True, False),
    ('fail', 'fail', False, False),
    ('pass', 'pass', False, True),
    ('skip', 'pass', False, False),
])
def test_phase_normalization_requires_the_named_source_control(tmp_path, control_status, generated_status, failed, passed):
    emission = {'phases': [], 'controls': [{'id': 'test_control', 'base_test_id': 'source'}],
                'obligations': [{'id': 'test_generated', 'base_test_id': 'source', 'control_ids': ['test_control']}]}
    for role, status, name in [('control', control_status, 'test_control'), ('generated', generated_status, 'test_generated')]:
        directory = tmp_path / role
        directory.mkdir()
        (directory / 'result.json').write_text(json.dumps({'returncode': 0}))
        (directory / 'events.jsonl').write_text('CC_RESULT ' + json.dumps({'id': name, 'status': status}) + '\n')
        emission['phases'].append({'role': role, 'report': {'format': 'jsonl', 'path': 'events.jsonl'}})
    (tmp_path / 'result.json').write_text('{}')
    result = normalize(tmp_path, emission, {})
    assert result['controlled_failure'] is failed
    assert result['controlled_pass'] is passed
