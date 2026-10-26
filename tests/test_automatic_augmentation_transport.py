"""Lossless transport recovery must not invent evidence or change test meaning."""
from copy import deepcopy
import json

import pytest

from scripts import normalize_automatic_augmentation_transport as transport
from scripts import run_automatic_augmentation_pilot as pilot


DIGEST = 'abcdef012345678901234567'
ALIAS = 'seed_' + DIGEST[:20]
TEST = 'test_' + DIGEST
CANDIDATES = [dict(seed_alias=ALIAS, evidence_id=TEST)]
KNOWN = {TEST, 'source_0123456789abcdef01234567', 'declaration_76543210fedcba9876543210'}


def goal():
    return dict(goal_id='G1', seed_alias=ALIAS, evidence_ids=[TEST],
                existing_validation='Existing test does A.', missing_relation='Missing A with B.',
                preconditions='Input is legal.', object_binding='The same object.',
                operations='Construct, operate, observe.', observation='Observe a field.',
                expectation='The field must equal 8.', oracle_basis='Original public issue.', missing_evidence=[])


def judgment():
    return dict(assessments=[dict(seed_aliases=[ALIAS], judgment='gap', scope='A with B.',
                                 reason='Original evidence supports it.', evidence_ids=[TEST])], goals=[goal()])


def test_only_exact_redundant_type_metadata_is_removed():
    value = dict(judgment(), type='json_object')
    normalized, changes = transport.normalize(json.dumps(value), CANDIDATES, KNOWN)
    assert normalized == judgment()
    assert changes == [dict(path='type', before='json_object', after=None,
                            rule='remove_redundant_exact_transport_metadata')]
    for extra in [dict(type='object'), dict(type='json_object', confidence=1), dict(type=None)]:
        value = dict(judgment(), **extra)
        normalized, changes = transport.normalize(json.dumps(value), CANDIDATES, KNOWN)
        assert normalized == value and not changes


def test_unique_prefixes_change_only_reference_fields():
    value = judgment()
    value['assessments'][0]['seed_aliases'] = ['seed_'+DIGEST[:16]]
    value['assessments'][0]['evidence_ids'] = ['test_'+DIGEST[:16]]
    value['goals'][0]['seed_alias'] = 'seed_'+DIGEST
    value['goals'][0]['evidence_ids'] = ['source_0123456789abcdef']
    # Strings that look like references are literal semantic text here.
    for field in ['scope', 'reason']:
        value['assessments'][0][field] = 'test_'+DIGEST[:16]
    for field in ['existing_validation', 'missing_relation', 'preconditions', 'object_binding',
                  'operations', 'observation', 'expectation', 'oracle_basis']:
        value['goals'][0][field] = 'seed_'+DIGEST
    before = deepcopy(value)
    normalized, changes = transport.normalize(json.dumps(value), CANDIDATES, KNOWN)
    assert value == before
    assert normalized['assessments'][0]['seed_aliases'] == [ALIAS]
    assert normalized['assessments'][0]['evidence_ids'] == [TEST]
    assert normalized['goals'][0]['seed_alias'] == ALIAS
    assert normalized['goals'][0]['evidence_ids'] == ['source_0123456789abcdef01234567']
    assert len(changes) == 4
    for old, new in zip(value['assessments'], normalized['assessments']):
        assert {k:v for k,v in old.items() if k not in {'seed_aliases','evidence_ids'}} == {k:v for k,v in new.items() if k not in {'seed_aliases','evidence_ids'}}
    for old, new in zip(value['goals'], normalized['goals']):
        assert {k:v for k,v in old.items() if k not in {'seed_alias','evidence_ids'}} == {k:v for k,v in new.items() if k not in {'seed_alias','evidence_ids'}}


@pytest.mark.parametrize('value', ['test_'+DIGEST[:15], 'test_abcxef0123456789',
                                  'source_'+DIGEST[:16], 'TEST_'+DIGEST[:16],
                                  'test_'+DIGEST+'0', 'seed_'+DIGEST[:-1]+'0',
                                  'seed_'+DIGEST+'0000', None, 9])
def test_short_wrong_namespace_fuzzy_or_unprovided_reference_is_unchanged(value):
    assert transport.canonical_reference(value, KNOWN | {ALIAS}, CANDIDATES) == value


def test_ambiguous_prefix_is_not_resolved():
    prefix = 'test_' + DIGEST[:16]
    permitted = {TEST, prefix + 'ffffffff'}
    assert transport.canonical_reference(prefix, permitted, CANDIDATES) == prefix


def test_expanded_seed_must_be_its_supplied_test_digest():
    assert transport.canonical_reference('seed_'+DIGEST, {ALIAS}, CANDIDATES) == ALIAS
    assert transport.canonical_reference('seed_'+DIGEST, {ALIAS}, []) == 'seed_'+DIGEST
    unrelated = [dict(seed_alias=ALIAS, evidence_id='source_'+DIGEST)]
    assert transport.canonical_reference('seed_'+DIGEST, {ALIAS}, unrelated) == 'seed_'+DIGEST
    missing = [dict(seed_alias=ALIAS, evidence_id=TEST)]
    assert transport.canonical_reference('seed_'+DIGEST, set(), missing) == 'seed_'+DIGEST


def test_duplicate_aliases_and_goals_are_not_silently_repaired():
    value = judgment()
    value['assessments'][0]['seed_aliases'] = [ALIAS, 'seed_'+DIGEST]
    value['goals'].append(deepcopy(value['goals'][0]))
    normalized, _ = transport.normalize(json.dumps(value), CANDIDATES, KNOWN)
    assert normalized['assessments'][0]['seed_aliases'] == [ALIAS, ALIAS]
    assert len(normalized['goals']) == 2
    parsed = pilot.parse_judgment(json.dumps(normalized), 'stop', {ALIAS}, KNOWN)
    assert parsed['status'] == 'unknown' and not parsed['goals']


def test_generation_never_changes_source_assertions_imports_or_goal_id():
    code = 'test("seed_'+DIGEST+'", () => { expect(value).toBe(999); });'
    value = dict(type='json_object', tests=[dict(goal_id='test_'+DIGEST[:16],
                 seed_alias='seed_'+DIGEST, rewritten_test=code,
                 imports=[dict(name='newApi', module='./source_'+DIGEST[:16], imported_name='actual')])])
    normalized, changes = transport.normalize(json.dumps(value), CANDIDATES, KNOWN, 'generation')
    assert normalized['tests'][0] == dict(value['tests'][0], seed_alias=ALIAS)
    assert len(changes) == 2


def test_invalid_json_duplicate_keys_and_unknown_refs_stay_invalid():
    with pytest.raises(ValueError, match='duplicate_json_key'):
        transport.normalize('{"tests":[],"tests":[]}', CANDIDATES, KNOWN, 'generation')
    value = judgment()
    value['goals'][0]['evidence_ids'] = ['test_ffffffffffffffff']
    normalized, _ = transport.normalize(json.dumps(value), CANDIDATES, KNOWN)
    assert pilot.parse_judgment(json.dumps(normalized), 'stop', {ALIAS}, KNOWN)['status'] == 'unknown'
