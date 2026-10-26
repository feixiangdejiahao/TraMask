"""Synthetic I/O protocol checks. No provider or target program is executed."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

from anchor_retrieval.syntax import Source
from relational_gap.frontend import extract_frontend, to_emitter_corpus
from research_tools import automatic_augmentation_provider as provider
from scripts import run_automatic_augmentation_io_repair as repair
from scripts import run_automatic_augmentation_pilot as original


def payload_pair():
    seed = dict(seed_alias='seed_long_0123456789', base_test_id='test_a.py:1:test_a',
                original_test='def test_a():\n    assert "seed_long_0123456789" != "source_long_abcdef"',
                evidence_id='test_long_abcdef', evidence_ids=['source_long_abcdef'])
    source = dict(seeds=[seed], public_issue='source_long_abcdef', submitted_patch='seed_long_0123456789',
        original_source_files=[dict(evidence_id='source_long_abcdef', text=seed['original_test'])],
        ordinary_entity={'id': 'source_long_abcdef', 'name': 'seed_long_0123456789'},
        nested_refs={'evidence_ids': ['source_long_abcdef'], 'seed_aliases': ['seed_long_0123456789']})
    history = dict(source, trajectory_evidence=dict(steps=[dict(evidence_id='step_long_abcdef',
        public_step=dict(message='source_long_abcdef', tool_calls=[dict(arguments={'command': 'seed_long_0123456789'})],
                         observation={'content': 'test_long_abcdef'}))],
        seed_associations=[dict(seed_alias=seed['seed_alias'], step_evidence_ids=['step_long_abcdef'])]))
    return source, history, [seed]


def test_short_ids_are_reversible_source_prefix_identical_and_content_untouched():
    source, history, seeds = payload_pair()
    src, hist, mapping = repair.shorten_batch(source, history, seeds)
    assert src['seeds'][0]['seed_alias'] == 'S001'
    assert src['seeds'][0]['base_test_id'] == seeds[0]['base_test_id']
    assert repair.replace_references(src, mapping['reverse']) == source
    assert repair.replace_references(hist, mapping['reverse']) == history
    assert repair.protected_content(source) == repair.protected_content(src)
    assert repair.protected_content(history) == repair.protected_content(hist)
    assert src['ordinary_entity'] == source['ordinary_entity']
    assert src['nested_refs']['seed_aliases'] == ['S001']
    assert hist['trajectory_evidence']['seed_associations'][0]['seed_alias'] == 'S001'
    assert hist['trajectory_evidence']['seed_associations'][0]['step_evidence_ids'] == [mapping['forward']['step_long_abcdef']]
    prefix = dict(hist); prefix.pop('trajectory_evidence')
    assert repair.canonical(prefix) == repair.canonical(src)
    assert set(repair.evidence_ids(src)).isdisjoint(set(mapping['history_only_evidence_ids']))


def test_source_numbering_does_not_change_with_extra_history_evidence():
    source, history, seeds = payload_pair()
    first = repair.shorten_batch(source, history, seeds)
    history['trajectory_evidence']['extra'] = {'evidence_id': '000_earlier_lexical_history'}
    second = repair.shorten_batch(source, history, seeds)
    assert first[0] == second[0]
    for identifier in repair.evidence_ids(source):
        assert first[2]['forward'][identifier] == second[2]['forward'][identifier]


@pytest.mark.parametrize('change', ['source_prefix', 'candidate_identity', 'duplicate_alias'])
def test_mapping_rejects_identity_changes(change):
    source, history, seeds = payload_pair()
    if change == 'source_prefix':
        history['public_issue'] = 'different issue'
    elif change == 'candidate_identity':
        seeds = [dict(seeds[0], base_test_id='other')]
    else:
        seeds = [*seeds, *seeds]; source['seeds'] = seeds; history['seeds'] = seeds
    with pytest.raises(ValueError):
        repair.shorten_batch(source, history, seeds)


def assessment(alias='S001', evidence='E0001', judgment='gap'):
    return dict(seed_aliases=[alias], judgment=judgment, scope='A second arithmetic input',
                reason='The supplied contract covers the second input.', evidence_ids=[evidence])


def goal(alias='S001', evidence='E0001'):
    return dict(goal_id='G1', seed_alias=alias, evidence_ids=[evidence],
        existing_validation='One input is checked.', missing_relation='A second input is not checked.',
        preconditions='A legal integer.', object_binding='The local function result.',
        operations='Call twice.', observation='Read the result.', expectation='Twice the input.',
        oracle_basis='Public arithmetic contract.', missing_evidence=[])


def test_exact_type_wrapper_only_and_no_fuzzy_schema_repair():
    obj = dict(type='json_object', assessments=[assessment()], goals=[goal()])
    raw = json.dumps(obj)
    normalized, changed = repair.strip_exact_type(raw)
    assert changed and json.loads(normalized) == {k: v for k, v in obj.items() if k != 'type'}
    assert repair.parse_judgment(raw, 'stop', {'S001'}, {'E0001'})['status'] == 'decoded'
    for wrong in [dict(obj, type='object'), dict(obj, additional='no'),
                  dict(obj, assessments=[dict(assessment(), extra='no')])]:
        assert repair.parse_judgment(json.dumps(wrong), 'stop', {'S001'}, {'E0001'})['status'] == 'unknown'
    assert repair.parse_judgment(raw, 'length', {'S001'}, {'E0001'})['status'] == 'unknown'
    assert repair.parse_judgment(raw, 'stop', {'S002'}, {'E0001'})['status'] == 'unknown'
    assert repair.parse_judgment(raw, 'stop', {'S001'}, {'E9999'})['status'] == 'unknown'
    duplicate = '{"type":"json_object","type":"json_object","assessments":[],"goals":[]}'
    assert repair.strip_exact_type(duplicate) == (duplicate, False)


def test_generation_type_cleanup_preserves_complete_test_text():
    code = 'def test_a():\n    assert "\\u2028" == "\\u2028"\n'
    content = json.dumps(dict(type='json_object', tests=[dict(goal_id='G1', seed_alias='S001', rewritten_test=code, imports=[])]))
    normalized, used = repair.strip_exact_type(content)
    assert used and json.loads(normalized)['tests'][0]['rewritten_test'] == code


def test_request_keeps_semantic_system_and_fixed_64k_both_stages():
    for stage, system in [('judgment', original.JUDGMENT_SYSTEM), ('generation', original.GENERATION_SYSTEM)]:
        req = repair.request(system, {'example': 'payload'}, stage)
        assert req['system'] == system
        assert req['max_tokens'] == 65536
        assert req['thinking'] == 'enabled' and req['reasoning_effort'] == 'low'
        assert req['kind'] == repair.VERSION + '.' + stage


def original_fixture(tmp_path):
    root = tmp_path / 'original'; source_dir = tmp_path / 'source'
    source, history, seeds = payload_pair()
    for name, value in [('source_payload', source), ('history_payload', history), ('extraction', {'seeds': seeds}),
                        ('trajectory', {'steps': []}), ('patch', {'patch': 'original'}), ('corpus.json', {'sources': {}})]:
        original.write(source_dir / name, value)
    batch = dict(batch_id='B01', candidates=seeds,
                 source_payload=original.receipt(source_dir / 'source_payload'),
                 history_payload=original.receipt(source_dir / 'history_payload'))
    case = dict(case='SYNTHETIC', source=str(source_dir), repository=str(tmp_path / 'repository'),
        extraction=original.receipt(source_dir / 'extraction'),
        inputs={'corpus.json': original.receipt(source_dir / 'corpus.json')},
        trajectory=original.receipt(source_dir / 'trajectory'), patch=original.receipt(source_dir / 'patch'), batches=[batch])
    protocol = dict(algorithm=[], arms=original.ARMS, repeats=3, cases=[case], judgments=6)
    original.write(root / 'prepared.json', protocol); original.write(root / 'seal.json', original.receipt(root / 'prepared.json'))
    return root


def test_prepare_and_reload_verify_old_inputs_and_reversible_projection(tmp_path):
    old = original_fixture(tmp_path); output = tmp_path / 'repair'
    assert repair.prepare(output, old) == {'cases': 1, 'batches': 1, 'judgments': 6}
    protocol = repair.load_protocol(output)
    assert protocol['max_output_tokens'] == 65536 and protocol['model'] == 'deepseek-flash'
    assert protocol['cases'][0]['batches'][0]['candidates'][0]['seed_alias'] == 'S001'
    old_protocol = original.read(old / 'prepared.json')
    assert old_protocol['cases'][0]['batches'][0]['candidates'][0]['seed_alias'].startswith('seed_long_')
    path = Path(protocol['cases'][0]['batches'][0]['identifier_map']['path'])
    path.write_text('{}')
    with pytest.raises(ValueError, match='changed_frozen_input'):
        repair.load_protocol(output)


@pytest.mark.parametrize('rewritten,expected', [
    ('def test_value():\n    assert double(4) == 8', 1),
    ('def test_value():\n    assert double(4) == 8\n\ndef escaped():\n    return 1', 0),
])
def test_new_work_item_uses_new_provider_short_alias_and_original_executor(tmp_path, monkeypatch, rewritten, expected):
    code = 'def double(value):\n    return value * 2\n\ndef test_value():\n    assert double(3) == 6\n'
    corpus = to_emitter_corpus(extract_frontend([Source('test_value.py', code, 'python')]))
    tid = next(iter(corpus['tests']))
    sp = corpus['tests'][tid]['span']; full = code.encode()[sp['start_byte']:sp['end_byte']].decode()
    seed = dict(seed_alias='long_seed', base_test_id=tid, original_test=full, evidence_id='long_test')
    src = dict(seeds=[seed], original_source_files=[dict(evidence_id='long_source', text=code)])
    hist = dict(src, trajectory_evidence={'steps': []})
    src, hist, mapping = repair.shorten_batch(src, hist, [seed])
    source_dir = tmp_path / 'source'; original.write(source_dir / 'corpus.json', corpus)
    original.write(tmp_path / 'source.json', src); original.write(tmp_path / 'history.json', hist)
    batch = dict(batch_id='B01', candidates=src['seeds'], source_payload=original.receipt(tmp_path / 'source.json'),
                 history_payload=original.receipt(tmp_path / 'history.json'))
    case = dict(case='SYNTHETIC', source=str(source_dir), repository=str(tmp_path / 'repository'),
                inputs={'corpus.json': original.receipt(source_dir / 'corpus.json')})
    requests = []
    def fake_dispatch(req, output, *, root):
        output.mkdir(parents=True); requests.append(req)
        assert req['max_tokens'] == 65536
        eid = mapping['forward']['long_source']
        if req['kind'].endswith('.judgment'):
            obj = dict(type='json_object', assessments=[assessment(evidence=eid)], goals=[goal(evidence=eid)])
        else:
            payload = json.loads(req['prompt'])
            assert payload['frozen_goals'] == [goal(evidence=eid)]
            assert payload['original_evidence'] == src
            obj = dict(type='json_object', tests=[dict(goal_id='G1', seed_alias='S001',
                rewritten_test=rewritten, imports=[])])
        content = json.dumps(obj)
        (output / 'completion.txt').write_text(content); (output / 'response.body').write_text(content)
        original.write(output / 'manifest.json', dict(status='complete', finish_reason='stop',
            external_model_calls=1, response_model='mock-canonical', usage={'total_tokens': 10}))
    monkeypatch.setattr(provider, 'dispatch', fake_dispatch)
    monkeypatch.setattr(original, 'dispatch_once', lambda *a, **k: pytest.fail('old provider path called'))
    result = repair.work_item(tmp_path / 'repair', case, batch, 'source_only', 1)
    assert len(requests) == 2 and result['provider_calls'] == 2
    assert result['judgment_status'] == 'decoded' and result['candidates'] == expected
    decoded = original.read(result['decoded']['path'])
    if expected:
        assert decoded['candidates'][0]['base_test_id'] == tid
    else:
        assert decoded['rejected']
    assert original.read(tmp_path / 'repair/cases/SYNTHETIC/B01/source_only/repeat_1/generation/io_normalization.json')['applied']


class Response:
    status_code = 200
    def __init__(self, body): self.body = body
    def __enter__(self): return self
    def __exit__(self, *args): return False
    def iter_bytes(self): yield self.body
    def raise_for_status(self): return None


def provider_fixture(tmp_path, monkeypatch, body):
    (tmp_path / 'configs').mkdir(); (tmp_path / 'results').mkdir()
    (tmp_path / 'configs/execution_policy.json').write_text('{"allow_model_code_upload":true}')
    (tmp_path / 'results/api_route.json').write_text('{"prefix":"v1/"}')
    monkeypatch.setattr(provider, 'dotenv_values', lambda p: {'BASE_URL': 'https://provider.example', 'API_KEY': 'SECRET_TEST_VALUE'})
    calls = []
    class Client:
        def __init__(self, **kwargs): calls.append(('client', kwargs))
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def stream(self, *args, **kwargs): calls.append(('wire', args, kwargs)); return Response(body)
    monkeypatch.setattr(provider.httpx, 'Client', Client)
    return calls


def test_provider_uses_canonical_model_route_64k_and_600_seconds_without_secret_receipt(tmp_path, monkeypatch):
    body = json.dumps({'model': 'deepseek-flash', 'choices': [{'finish_reason': 'stop', 'message': {'content': '{}'}}],
                       'usage': {'total_tokens': 8}}).encode()
    calls = provider_fixture(tmp_path, monkeypatch, body)
    req = repair.request('semantic system', {}, 'judgment')
    record = provider.dispatch(req, tmp_path / 'call', root=tmp_path)
    assert record['status'] == 'complete' and record['external_model_calls'] == 1
    assert calls[0] == ('client', {'timeout': 600, 'follow_redirects': False})
    assert calls[1][1] == ('POST', 'https://provider.example/v1/chat/completions')
    wire = json.loads(calls[1][2]['content'])
    assert wire['model'] == 'deepseek-flash' and wire['max_tokens'] == 65536 and wire['temperature'] == 0
    assert wire['thinking'] == {'type': 'enabled'} and wire['reasoning_effort'] == 'low'
    assert 'SECRET_TEST_VALUE' not in (tmp_path / 'call/manifest.json').read_text()
    assert record['response_sha256'] == hashlib.sha256(body).hexdigest()
    with pytest.raises(FileExistsError):
        provider.dispatch(req, tmp_path / 'call', root=tmp_path)
    assert len([x for x in calls if x[0] == 'wire']) == 1


def test_provider_response_bound_records_failure_without_retry(tmp_path, monkeypatch):
    calls = provider_fixture(tmp_path, monkeypatch, b'x' * (provider.MAX_RESPONSE_BYTES + 20))
    record = provider.dispatch(repair.request('system', {}, 'judgment'), tmp_path / 'call', root=tmp_path)
    assert record['status'] == 'error' and record['response_body_truncated']
    assert (tmp_path / 'call/response.body').stat().st_size == provider.MAX_RESPONSE_BYTES
    assert record['external_model_calls'] == 1
    assert len([x for x in calls if x[0] == 'wire']) == 1


@pytest.mark.parametrize('limit', [65537, True, 0])
def test_provider_rejects_invalid_output_limit_before_network(tmp_path, limit):
    req = repair.request('system', {}, 'judgment'); req['max_tokens'] = limit
    with pytest.raises(ValueError, match='Unsupported output token budget'):
        provider.dispatch(req, tmp_path / 'call', root=tmp_path)
