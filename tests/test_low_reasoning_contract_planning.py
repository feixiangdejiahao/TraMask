import copy

from scripts import run_low_reasoning_contract_planning as low


def test_only_reasoning_effort_and_request_identity_change(monkeypatch):
    request = dict(system='source selection', prompt='{"declarations":[]}',
        thinking='enabled', reasoning_effort='high', max_tokens=8192)
    request['id'] = request['query_sha256'] = low.original.planning.core._identity(request)
    prepared = dict(request=request, seeds=['unchanged'], omitted=['unchanged'],
        source_sha256={'source':'unchanged'}, catalog_bytes=123, prompt_bytes=100)
    monkeypatch.setattr(low.original.planning, 'prepare', lambda *a, **k: copy.deepcopy(prepared))
    actual = low.planning_prepare({}, {})
    expected = copy.deepcopy(prepared)
    expected['request']['reasoning_effort'] = 'low'
    expected['request']['id'] = expected['request']['query_sha256'] = low.original.planning.core._identity(expected['request'])
    assert actual == expected
    assert actual['request']['id'] != request['id']
    assert prepared['request']['reasoning_effort'] == 'high'


def test_stage_namespace_keeps_low_policy_and_original_generation_budget():
    functions = low.engine()
    assert functions['PLANNING_POLICY'] == dict(low.original.PLANNING_POLICY, reasoning_effort='low')
    assert functions['plan'].__globals__ is functions
    assert functions['prepare_generation'].__globals__ is functions
    assert functions['planning'].prepare is low.planning_prepare
    generation = functions['_engine']()
    assert generation['VERSION'] == low.VERSION
    assert generation['relation'] is low.original.relation
    assert generation['_verify_protocol'] is functions['_verify_protocol']


def test_unavailable_source_request_stays_unavailable(monkeypatch):
    prepared = dict(request=None, status='planning_input_unavailable')
    monkeypatch.setattr(low.original.planning, 'prepare', lambda *a, **k: copy.deepcopy(prepared))
    assert low.planning_prepare({}, {}) == prepared
