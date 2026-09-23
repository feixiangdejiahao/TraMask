import copy
import hashlib
import json

import pytest

from combination_testing.screening import choose_proposals, freeze_screened, prepare


def proposal(line, coordinate, followup, identifier):
    packet = {'key': '97u', 'alternate': [], 'modifiers': 1, 'phase': '1', 'text': []}
    return {'id': identifier, 'source_assertion': {'path': 'tests/a.py', 'line': line},
            'source_packet': packet, 'followup_packet': {**packet, **followup},
            'field': 'value', 'op': 'eq', 'expected': 'original', 'changed_coordinate': coordinate}


def test_sampling_rotates_assertions_and_coordinates():
    selection = {'anchors': [{'id': 'a', 'path': 'tests/a.py', 'line': 1},
                             {'id': 'b', 'path': 'tests/a.py', 'line': 2}],
                 'rankings': {'full': ['a', 'b']}}
    candidates = [proposal(1, 'key', {'key': key}, f'a{i}')
                  for i, key in enumerate(['98u', '15~', '1A', '1B', '13u'])]
    candidates += [proposal(1, 'text', {'text': ['98']}, 'a_text'),
                   proposal(2, 'text', {'text': ['99']}, 'b_text')]
    generated = {'candidates': candidates, 'metadata': {'coordinates': ['key', 'text']}}
    chosen, metadata = choose_proposals(generated, selection, budget=3)
    assert chosen[0]['changed_coordinate'] == 'key'
    assert [item['id'] for item in chosen[1:]] == ['b_text', 'a_text']
    assert metadata['sent_proposals'] == 3
    assert len(candidates) == 7


def test_freezing_executes_only_approved_concrete_proposals(tmp_path):
    cache = tmp_path / 'cache'
    cache.mkdir()
    source = {'sequence': '\x1b[97u', 'field': 'value', 'op': 'eq', 'expected': 10, 'id': 'seed'}
    first = {**source, 'sequence': '\x1b[97;1:2u', 'id': 'first', 'seed': source['sequence']}
    second = {**source, 'sequence': '\x1b[98u', 'id': 'second', 'seed': source['sequence']}
    data = {'chosen': [first, second], 'controls': [source], 'sampling': {},
            'adapter': {'module': 'subject', 'class': 'Parser', 'method': 'feed'}}
    (cache / 'proposals.json').write_text(json.dumps(data))
    (cache / 'approved.json').write_text('["c0001"]')
    manifest = {'valid': True, 'case_id': 'synthetic',
                'proposal_sha256': hashlib.sha256((cache / 'proposals.json').read_bytes()).hexdigest(),
                'approval_sha256': hashlib.sha256((cache / 'approved.json').read_bytes()).hexdigest()}
    (cache / 'manifest.json').write_text(json.dumps(manifest))
    frozen = freeze_screened(cache, tmp_path / 'frozen')
    assert [row['id'] for row in frozen['metadata']['obligations']] == ['second']
    assert frozen['metadata']['obligations'][0]['expected'] == 10
    assert frozen['metadata']['obligations'][0]['controls'] == ['seed']
    (cache / 'approved.json').write_text('["c0000","c0001"]')
    with pytest.raises(ValueError, match='changed'):
        freeze_screened(cache, tmp_path / 'tampered')


def test_calibration_labels_are_local_and_known_contradictions_are_vetoed(tmp_path, monkeypatch):
    from combination_testing.protocol import Packet
    facts = [{'sequence': '\x1b[42;1:1u', 'field': 'value', 'op': 'eq', 'expected': 1,
              'source': {'path': 'tests/a.py', 'line': 1}},
             {'sequence': '\x1b[42;1:2u', 'field': 'value', 'op': 'eq', 'expected': 2,
              'source': {'path': 'tests/a.py', 'line': 2}},
             {'sequence': '\x1b[43;1:1u', 'field': 'value', 'op': 'eq', 'expected': 1,
              'source': {'path': 'tests/a.py', 'line': 3}}]
    wrong = {'id': 'bad', 'source_packet': Packet.parse(facts[0]['sequence']).as_dict(),
             'followup_packet': Packet.parse(facts[1]['sequence']).as_dict(),
             'seed': facts[0]['sequence'], 'sequence': facts[1]['sequence'],
             'field': 'value', 'op': 'eq', 'expected': 1, 'source_assertion': facts[0]['source'],
             'changed_coordinate': 'event_type'}
    generated = {'candidates': [wrong], 'controls': facts, 'adapter': {},
                 'metadata': {'facts': facts, 'coordinates': ['event_type', 'key_representation']}}
    monkeypatch.setattr('combination_testing.screening.generate_protocol_transports', lambda *a: generated)
    selection = {'anchors': [], 'rankings': {'full': []}}
    _, chosen, sampling, evidence = prepare(tmp_path, selection, 'Issue')
    assert sampling['existing_fact_vetoes'] == 1
    assert all(row['id'] != 'bad' for row in chosen)
    assert {row['expected_admission'] for row in chosen} == {True, False}
    assert 'expected_admission' not in json.dumps(evidence)
    assert 'calibration_evidence' not in json.dumps(evidence)
