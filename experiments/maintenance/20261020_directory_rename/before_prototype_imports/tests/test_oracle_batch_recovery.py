import copy
import hashlib
import json

import pytest

from anchor_retrieval.syntax import Source
from experimental.oracle_batch_recovery import plan_recovery, recovery_condition, validate_frozen_request
from relational_gap.frontend import extract_frontend, to_emitter_corpus
from relation_search.oracle import prepare_requests, validate


def batch():
    source = Source('test_numbers.py', '''def test_count():
    values = [1]
    result = len(values)
    assert result == 1
    assert result > 0
''', 'python')
    front = extract_frontend([source])
    corpus = to_emitter_corpus(front)
    test = next(iter(corpus['tests'].values()))
    at = source.code.index('[1]')
    candidates = [dict(id='input_'+str(n), base_test_id=test['id'], source_test_ids=[], imports=[],
                       source_contexts=[dict(code='Do not translate this: 中文')],
                       edits=[dict(span=dict(path=source.path, start_byte=at, end_byte=at+3),
                                   before='[1]', after=repr(list(range(n))), role='input')])
                  for n in (2, 3, 4)]
    request = prepare_requests(corpus, front, candidates, 'Count the items: 计数.')[0]
    request['source_prepared'] = '/frozen/input'
    return corpus, request


def completed(request, **kwargs):
    return dict(request_id=request['id'], status='complete', finish_reason='stop', **kwargs)


def rehash(request):
    request['id'] = hashlib.sha256(request['prompt'].encode()).hexdigest()
    request['candidate_source_hash'] = hashlib.sha256(json.dumps(request['offered'], sort_keys=True).encode()).hexdigest()


def test_singletons_preserve_exact_sources_and_assertion_mapping_and_validate():
    corpus, parent = batch()
    original = copy.deepcopy(parent)
    manifest = completed(parent)
    manifest_original = copy.deepcopy(manifest)
    plan = plan_recovery(parent, manifest, '{"revisions": [')
    assert plan['eligible'] and plan['reason'] == 'completed_invalid_json'
    assert len(plan['requests']) == 3
    original_payload = json.loads(parent['prompt'])
    for ordinal, child in enumerate(plan['requests']):
        alias = 'C'+str(ordinal)
        wire = json.loads(child['prompt'])
        expected = copy.deepcopy(original_payload['candidates'][ordinal])
        expected['candidate'] = 'C0'
        assert wire['candidates'] == [expected]
        assert {k: v for k, v in wire.items() if k != 'candidates'} == {
            k: v for k, v in original_payload.items() if k != 'candidates'}
        assert child['offered'] == {'C0': parent['offered'][alias]}
        for key in parent.keys() - {'id', 'prompt', 'offered', 'candidate_source_hash'}:
            assert child[key] == parent[key]
        assert child['batch_recovery']['depth'] == 1
        assert child['batch_recovery']['parent_alias'] == alias
        result = validate(child, {'revisions': [{'candidate': 'C0', 'basis': 'Input has the stated number of items.',
                           'updates': [{'assertion': 'A0', 'code': f'assert result == {ordinal + 2}'}]}]}, corpus)
        assert result['revisions'][0]['semantic_revision']['parent'] == parent['offered'][alias]['candidate']['id']
        assert result['revisions'][0]['edits'][0] == parent['offered'][alias]['candidate']['edits'][0]
        assert result['revisions'][0]['edits'][-1]['before'] == 'assert result == 1'
    assert parent == original and manifest == manifest_original
    assert plan == plan_recovery(parent, manifest, '{"revisions": [')
    # No mutable child aliases leak back into another child or its parent.
    plan['requests'][0]['offered']['C0']['candidate']['edits'][0]['after'] = 'mutated'
    assert parent == original
    assert plan['requests'][1]['offered']['C0']['candidate'] == parent['offered']['C1']['candidate']


@pytest.mark.parametrize('status', ['error', 'dispatching', 'prepared', 'configuration_error'])
def test_transport_or_incomplete_records_never_retry(status):
    _, request = batch()
    manifest = dict(request_id=request['id'], status=status, error_type='ReadTimeout', finish_reason='length')
    result = plan_recovery(request, manifest, None)
    assert not result['eligible'] and result['requests'] == []
    assert result['reason'] == 'provider_not_complete'


def test_length_finish_can_split_complete_json_but_split_children_never_retry():
    _, request = batch()
    manifest = completed(request)
    manifest['finish_reason'] = 'length'
    plan = plan_recovery(request, manifest, '{"revisions": []}')
    assert plan['reason'] == 'completed_length_limit' and len(plan['requests']) == 3
    for child in plan['requests']:
        child_manifest = completed(child)
        child_manifest['finish_reason'] = 'length'
        again = plan_recovery(child, child_manifest, '')
        assert not again['eligible'] and again['reason'] == 'already_split'
        assert again['requests'] == []


@pytest.mark.parametrize('text', ['{"revisions": []}', '{}', 'null', '[]', '"refusal"',
                                 '{"revisions": [{"candidate": "C0", "updates": [], "basis": "unknown"}]}'])
def test_valid_json_semantic_or_schema_failure_does_not_trigger_recovery(text):
    _, request = batch()
    assert recovery_condition(request, completed(request), text) == (False, 'completed_parseable_json')


def test_original_single_candidate_failure_is_not_retried():
    _, parent = batch()
    child = plan_recovery(parent, completed(parent), '')['requests'][0]
    del child['batch_recovery']
    assert recovery_condition(child, completed(child), '') == (False, 'already_singleton')


def test_manifest_must_belong_to_request():
    _, request = batch()
    manifest = completed(request)
    manifest['request_id'] = 'another request'
    with pytest.raises(ValueError, match='different request'):
        plan_recovery(request, manifest, '')


@pytest.mark.parametrize('field', ['prompt', 'offered'])
def test_hash_tampering_is_rejected(field):
    _, request = batch()
    if field == 'prompt':
        request['prompt'] += ' '
    else:
        request['offered']['C0']['candidate']['edits'][0]['after'] = '[999]'
    with pytest.raises(ValueError, match='hash changed'):
        plan_recovery(request, completed(request), '')


@pytest.mark.parametrize('mutation', ['missing_candidate', 'duplicate_candidate', 'assertion_code', 'assertion_id',
                                     'input_edit', 'source_test', 'issue'])
def test_wire_mapping_inconsistency_is_rejected_even_with_updated_hashes(mutation):
    _, request = batch()
    payload = json.loads(request['prompt'])
    first = payload['candidates'][0]
    if mutation == 'missing_candidate':
        payload['candidates'].pop()
    elif mutation == 'duplicate_candidate':
        payload['candidates'][1]['candidate'] = 'C0'
    elif mutation == 'assertion_code':
        first['assertions'][0]['code'] = 'assert False'
    elif mutation == 'assertion_id':
        first['assertions'][0]['id'] = 'A88'
    elif mutation == 'input_edit':
        first['input_changes'][0]['after'] = '[999]'
    elif mutation == 'source_test':
        first['source_test'] = 'other'
    else:
        payload['issue'] = 'different issue'
    request['prompt'] = json.dumps(payload)
    rehash(request)
    with pytest.raises(ValueError):
        validate_frozen_request(request)


def test_extra_payload_context_survives_without_retrieval():
    _, request = batch()
    payload = json.loads(request['prompt'])
    payload['extra_source_evidence'] = {'text': 'Already frozen context, including C2 and A1 as source text.'}
    payload['candidates'][2]['modified_test'] += '\n# literal C2/A1 must not be rewritten'
    request['prompt'] = json.dumps(payload, ensure_ascii=False)
    rehash(request)
    result = plan_recovery(request, completed(request), '')
    child_payload = json.loads(result['requests'][2]['prompt'])
    assert child_payload['extra_source_evidence'] == payload['extra_source_evidence']
    assert child_payload['candidates'][0]['modified_test'] == payload['candidates'][2]['modified_test']
