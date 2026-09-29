"""Independent paired-wire checks must reject confounded comparisons."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location('ablation_audit', Path(__file__).resolve().parents[1] / 'scripts/audit_dependency_context_ablation.py')
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))
    return hashlib.sha256(path.read_bytes()).hexdigest()


def pair_fixture(tmp_path, *, changed_assertion=False, changed_setting=False):
    candidate = dict(candidate='C0', modified_test='assert x == 1', dependency_evidence='source')
    treatment = dict(system='system', offered={'C0': {'candidate': {'id': 'candidate'}}}, prompt=json.dumps({'candidates': [candidate]}))
    control = copy.deepcopy(treatment)
    payload = json.loads(control['prompt'])
    del payload['candidates'][0]['dependency_evidence']
    if changed_assertion:
        payload['candidates'][0]['modified_test'] = 'assert x == 2'
    control['prompt'] = json.dumps(payload)
    pair = dict(candidate_id='candidate')
    for arm, request in [('treatment', treatment), ('control', control)]:
        request_path = tmp_path / (arm + '.json')
        pair[arm + '_request'] = str(request_path)
        pair[arm + '_request_sha256'] = save(request_path, request)
        folder = tmp_path / arm
        pair[arm + '_completion'] = str(folder)
        wire = dict(model='deepseek-v4-flash', temperature=0,
                    messages=[dict(role='system', content=request['system']), dict(role='user', content=request['prompt'])])
        if changed_setting and arm == 'control':
            wire['temperature'] = 1
        response = {'choices': [{'message': {'content': '{"revisions":[]}'}}]}
        request_sha = save(folder / 'request.json', wire)
        response_sha = save(folder / 'response.body', response)
        save(folder / 'response.json', response)
        save(folder / 'validation.json', dict(revisions=[], decisions=[]))
        save(folder / 'manifest.json', dict(request_sha256=request_sha, response_sha256=response_sha,
             model='deepseek-v4-flash', external_model_calls=1, seconds=0.1, usage={}, finish_reason='stop'))
    return pair


def test_accepts_only_dependency_removed(tmp_path):
    assert MODULE.verify_pair(pair_fixture(tmp_path))['verified_single_field_wire_intervention']


def test_rejects_assertion_change(tmp_path):
    with pytest.raises(AssertionError, match='more than dependency'):
        MODULE.verify_pair(pair_fixture(tmp_path, changed_assertion=True))


def test_rejects_model_setting_change(tmp_path):
    with pytest.raises(AssertionError, match='settings differ'):
        MODULE.verify_pair(pair_fixture(tmp_path, changed_setting=True))
