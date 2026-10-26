"""Independent trust-boundary checks for automatic augmentation.

Only synthetic source and mocked completions are used. No task labels, provider
calls, benchmark code execution, or frozen evaluation reference enters a test.
"""
import copy
import json
import sys
import types

import pytest

from anchor_retrieval.syntax import Source
from relational_gap.frontend import extract_frontend, to_emitter_corpus
from research_tools import automatic_augmentation_extract as extractor
from scripts import run_automatic_augmentation_pilot as pilot


def assessment(alias='S1', judgment='gap', evidence=('source_public',)):
    return dict(seed_aliases=[alias], judgment=judgment, scope='Changed-value observation',
                reason='The public relation and original assertion establish this scope.',
                evidence_ids=list(evidence))


def goal(alias='S1', identifier='G1'):
    return dict(goal_id=identifier, seed_alias=alias, evidence_ids=['source_public'],
                existing_validation='One input is observed.', missing_relation='A second value is not observed.',
                preconditions='A legal integer input.', object_binding='The same result of double.',
                operations='Call double with that input.', observation='Observe the returned integer.',
                expectation='The returned value is twice the input.',
                oracle_basis='Public arithmetic contract.', missing_evidence=[])


def parse(assessments=None, goals=None, aliases=('S1',), evidence=('source_public',)):
    payload = dict(assessments=assessments if assessments is not None else [assessment()],
                   goals=goals if goals is not None else [goal()])
    return pilot.parse_judgment(json.dumps(payload), 'stop', set(aliases), set(evidence))


def test_valid_gap_and_grouped_assessment_preserve_scoped_goals():
    row = assessment(); row['seed_aliases'] = ['S1', 'S2']
    result = parse([row], [goal('S2')], aliases=('S1', 'S2'))
    assert result['status'] == 'decoded'
    assert result['goals'] == [goal('S2')]
    assert result['unassessed_aliases'] == []
    assert result['semantic_validity'] == 'requires_independent_review'


@pytest.mark.parametrize('content,finish', [
    ('{"assessments": [], "goals": []}', 'length'),
    ('{"assessments": [], "goals": [], "goals": []}', 'stop'),
    ('{"assessments": [], "goals": [], "verdict": "no_gap"}', 'stop'),
    ('null', 'stop'), ('not json', 'stop'),
])
def test_incomplete_or_malformed_output_is_unknown_not_no_gap(content, finish):
    result = pilot.parse_judgment(content, finish, {'S1'}, {'source_public'})
    assert result['status'] == 'unknown'
    assert result['assessments'] == [] and result['goals'] == []


def test_missing_alias_stays_unassessed_instead_of_becoming_no_gap():
    result = parse([assessment(judgment='unknown', evidence=())], [], aliases=('S1', 'S2'))
    assert result['status'] == 'decoded'
    assert result['assessments'][0]['judgment'] == 'unknown'
    assert result['unassessed_aliases'] == ['S2']
    assert result['goals'] == []
    assert not any(r['judgment'] == 'no_gap' for r in result['assessments'])


@pytest.mark.parametrize('rows', [
    [assessment(), assessment()],
    [dict(assessment(), seed_aliases=['S1', 'S1'])],
    [assessment('not_supplied')],
    [dict(assessment(), judgment='probably_gap')],
])
def test_invalid_assessment_membership_cannot_supply_a_goal(rows):
    result = parse(rows)
    assert result['status'] == 'unknown' and result['goals'] == []


@pytest.mark.parametrize('judgment', ['no_gap', 'unknown'])
def test_goal_cannot_use_a_seed_without_a_gap_assessment(judgment):
    result = parse([assessment('S1'), assessment('S2', judgment)], [goal('S2')], aliases=('S1', 'S2'))
    assert result['status'] == 'unknown' and result['goals'] == []


def test_history_evidence_is_not_valid_in_the_source_only_arm():
    rows = [assessment(evidence=('step_history',))]
    g = dict(goal(), evidence_ids=['step_history'])
    plain = parse(rows, [g])
    history = parse(rows, [g], evidence=('source_public', 'step_history'))
    assert plain['status'] == 'unknown' and plain['goals'] == []
    assert history['status'] == 'decoded' and history['goals'] == [g]


@pytest.mark.parametrize('judgment', ['gap', 'no_gap'])
def test_decisive_assessment_requires_an_actual_evidence_citation(judgment):
    result = parse([assessment(judgment=judgment, evidence=())], [])
    assert result['status'] == 'unknown'


def test_data_object_ids_cannot_masquerade_as_evidence_identifiers():
    payload = dict(original_source_files=[dict(evidence_id='source_public', text='public source')],
                   trajectory_evidence=dict(steps=[dict(evidence_id='step_history',
                       public_step=dict(observation={'id': 'unregistered_data_id'}))]),
                   unrelated={'id': 'ordinary_entity_id'}, evidence_ids=['unregistered_list_entry'])
    assert pilot.evidence_ids(payload) == {'source_public', 'step_history'}


@pytest.mark.parametrize('changed', [
    {'missing_evidence': ['The called helper contract is missing.']},
    {'missing_evidence': [42]}, {'goal_id': '   '},
    {'expectation': ''}, {'evidence_ids': []},
    {'evidence_ids': ['invented_evidence']},
    {'test_code': 'def injected_test(): pass'},
])
def test_incomplete_or_unregistered_goal_cannot_become_runnable(changed):
    result = parse(goals=[dict(goal(), **changed)])
    assert result['goals'] == []


def synthetic_extraction():
    code = 'from api import double\n\ndef test_value():\n    assert double(3) == 6\n'
    api = 'def double(value):\n    """Return twice the input."""\n    return value * 2\n'
    sources = [Source('test_value.py', code, 'python', 'repository'),
               Source('api.py', api, 'python', 'repository'),
               Source('history_only.py', 'def test_history():\n    assert PRIVATE_OLD_SOURCE\n',
                      'python', 'trajectory')]
    frontend = extract_frontend(sources)
    corpus = to_emitter_corpus(frontend)
    corpus['evaluation_metadata'] = 'PRIVATE_EVALUATION'
    trajectory = dict(evaluation='PRIVATE_GLOBAL', steps=[dict(step_id=2,
        message='Read api.py before validating double. ORIGINAL_HISTORY_SENTINEL',
        reasoning_content='PRIVATE_REASONING', evaluation='PRIVATE_STEP_EVALUATION',
        tool_calls=[dict(function_name='bash', arguments={'command': 'cat api.py'})],
        observation={'results': [{'content': 'ORIGINAL_OBSERVATION_SENTINEL'}]})])
    patch = 'diff --git a/api.py b/api.py\n--- a/api.py\n+++ b/api.py\n@@ -1,3 +1,3 @@\n def double(value):\n     """Return twice the input."""\n-    return value\n+    return value * 2\n'
    result = extractor.extract(corpus, frontend, 'Return twice the supplied integer.', trajectory, patch)
    return result


def test_real_extractor_pair_has_identical_source_and_no_history_leakage():
    result = synthetic_extraction()
    plain = result['source_payload']; full = copy.deepcopy(result['history_payload'])
    history = full.pop('trajectory_evidence')
    assert result['candidates'] and history['steps']
    assert full == plain
    a, b = pilot.canonical(plain), pilot.canonical(result['history_payload'])
    assert 'ORIGINAL_HISTORY_SENTINEL' not in a and 'ORIGINAL_OBSERVATION_SENTINEL' not in a
    assert 'ORIGINAL_HISTORY_SENTINEL' in b and 'ORIGINAL_OBSERVATION_SENTINEL' in b
    assert 'PRIVATE_' not in a and 'PRIVATE_' not in b
    for arm in (plain, result['history_payload']):
        req = pilot.request(pilot.JUDGMENT_SYSTEM, arm, 'judgment')
        assert req['manual_labels_included'] is False
        assert req['later_research_outcomes_included'] is False


def work_fixture(tmp_path, monkeypatch, decision):
    source = tmp_path / 'source'
    pilot.write(source / 'corpus.json', {'synthetic': True})
    payload = {'seeds': [{'seed_alias': 'S1'}],
               'original_source_files': [{'evidence_id': 'source_public', 'text': 'PUBLIC_SOURCE'}]}
    pilot.write(tmp_path / 'source_payload.json', payload)
    pilot.write(tmp_path / 'history_payload.json', dict(payload,
        trajectory_evidence={'steps': [{'evidence_id': 'step_history', 'text': 'ORIGINAL_HISTORY'}]}))
    batch = dict(batch_id='B01', candidates=[dict(seed_alias='S1', base_test_id='test_value.py:3:test_value')],
                 source_payload=pilot.receipt(tmp_path / 'source_payload.json'),
                 history_payload=pilot.receipt(tmp_path / 'history_payload.json'))
    case = dict(case='SYNTHETIC', source=str(source), repository=str(tmp_path / 'repo'),
                inputs={'corpus.json': pilot.receipt(source / 'corpus.json')})
    calls, decoded_inputs = [], []
    adapter = types.ModuleType('scripts.execute_automatic_augmentation_pilot')
    def decode(corpus, record, response, finish):
        decoded_inputs.append(copy.deepcopy(record))
        return dict(status='decoded', candidates=[], rejected=[])
    adapter.decode = decode
    monkeypatch.setitem(sys.modules, adapter.__name__, adapter)
    import scripts
    monkeypatch.setattr(scripts, 'execute_automatic_augmentation_pilot', adapter, raising=False)
    def fake_dispatch(req, directory):
        calls.append(copy.deepcopy(req))
        if req['kind'].endswith('.judgment'):
            return json.dumps(decision), {'finish_reason': 'stop', 'external_model_calls': 1,
                                         'usage': {'total_tokens': 7}}
        frozen = directory.parent / 'judgment' / 'decision.json'
        seal = pilot.read(directory.parent / 'judgment' / 'decision_seal.json')
        pilot.verify(seal)
        assert seal == pilot.receipt(frozen)
        assert json.loads(req['prompt'])['frozen_goals'] == pilot.read(frozen)['goals']
        return '{"tests": []}', {'finish_reason': 'stop', 'external_model_calls': 1,
                                 'usage': {'total_tokens': 9}}
    monkeypatch.setattr(pilot, 'dispatch_once', fake_dispatch)
    return case, batch, calls, decoded_inputs


def test_generation_uses_the_sealed_goal_and_same_arm_evidence(tmp_path, monkeypatch):
    decision = dict(assessments=[assessment()], goals=[goal()])
    case, batch, calls, decoded = work_fixture(tmp_path, monkeypatch, decision)
    result = pilot.work_item(tmp_path, case, batch, 'source_only', 1)
    assert len(calls) == 2 and result['provider_calls'] == 2
    first, second = (json.loads(x['prompt']) for x in calls)
    assert second == {'original_evidence': first, 'frozen_goals': decision['goals']}
    assert 'ORIGINAL_HISTORY' not in calls[1]['prompt']
    assert decoded[0]['goals'] == decision['goals']
    assert decoded[0]['seeds'] == batch['candidates']


@pytest.mark.parametrize('decision', [
    {'assessments': [assessment(judgment='unknown', evidence=())], 'goals': []},
    {'assessments': [assessment(judgment='no_gap')], 'goals': []},
    {'assessments': [], 'goals': []},
])
def test_no_supported_goal_does_not_invent_an_augmentation_request(tmp_path, monkeypatch, decision):
    case, batch, calls, decoded = work_fixture(tmp_path, monkeypatch, decision)
    result = pilot.work_item(tmp_path, case, batch, 'source_only', 1)
    assert len(calls) == 1 and decoded == []
    assert result['generation_status'] == 'not_requested' and result['candidates'] == 0


@pytest.mark.parametrize('which', ['corpus.json', 'trajectory', 'patch'])
def test_loading_protocol_rejects_changed_original_input(tmp_path, which):
    refs = {}
    for name in ('corpus.json', 'trajectory', 'patch', 'extraction', 'source_payload', 'history_payload'):
        path = tmp_path / (name + '.fixture')
        pilot.write(path, {'original': name})
        refs[name] = pilot.receipt(path)
    case = dict(inputs={'corpus.json': refs['corpus.json']}, trajectory=refs['trajectory'],
                patch=refs['patch'], extraction=refs['extraction'], batches=[dict(
                    source_payload=refs['source_payload'], history_payload=refs['history_payload'])])
    pilot.write(tmp_path / 'prepared.json', {'algorithm': [], 'cases': [case]})
    pilot.write(tmp_path / 'seal.json', pilot.receipt(tmp_path / 'prepared.json'))
    from pathlib import Path
    Path(refs[which]['path']).write_text('{"changed": true}')
    with pytest.raises(ValueError, match='changed_frozen_input'):
        pilot.load_protocol(tmp_path)


def decoder_fixture():
    from scripts import execute_automatic_augmentation_pilot as adapter
    code = ('def test_value():\n    assert 2 + 2 == 4\n\n'
            'def test_other():\n    assert 3 + 3 == 6\n')
    corpus = to_emitter_corpus(extract_frontend([
        Source('test_value.py', code, 'python', 'repository')]))
    identifiers = sorted(corpus['tests'], key=lambda k: corpus['tests'][k]['span']['start_byte'])
    seeds = [dict(seed_alias=f'S{i}', base_test_id=tid) for i, tid in enumerate(identifiers, 1)]
    case = dict(seeds=seeds, goals=[goal()], max_candidates=2)
    return adapter, corpus, case


def proposal(alias='S1', identifier='G1', number=4):
    name = 'test_value' if alias == 'S1' else 'test_other'
    return dict(goal_id=identifier, seed_alias=alias,
                rewritten_test=f'def {name}():\n    assert {number} + {number} == {number * 2}',
                imports=[])


def test_real_decoder_rejects_wrong_goal_seed_without_losing_later_valid_test():
    adapter, corpus, case = decoder_fixture()
    result = adapter.decode(corpus, case,
        json.dumps({'tests': [proposal('S2'), proposal()]}), 'stop')
    assert len(result['candidates']) == 1
    assert result['candidates'][0]['order'] == [2]
    assert result['candidates'][0]['augmentation_provenance']['goal_id'] == 'G1'
    assert result['candidates'][0]['augmentation_provenance']['seed_alias'] == 'S1'
    assert result['rejected'] == [dict(rank=1, reason='goal_seed_binding_mismatch')]


def test_real_decoder_cannot_introduce_a_goal_not_in_the_frozen_decision():
    adapter, corpus, case = decoder_fixture()
    result = adapter.decode(corpus, case,
        json.dumps({'tests': [proposal(identifier='NEW_GOAL')]}), 'stop')
    assert result['candidates'] == []
    assert result['rejected'] == [dict(rank=1, reason='goal_seed_binding_mismatch')]


def test_real_decoder_accepts_at_most_one_complete_test_per_frozen_goal():
    adapter, corpus, case = decoder_fixture()
    result = adapter.decode(corpus, case,
        json.dumps({'tests': [proposal(number=4), proposal(number=5)]}), 'stop')
    assert len(result['candidates']) == 1
    assert result['candidates'][0]['order'] == [1]
    assert len(result['rejected']) == 1 and result['rejected'][0]['rank'] == 2
