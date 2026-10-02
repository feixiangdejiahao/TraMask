"""Source provenance audits must detect altered text, roles, and projections."""
from copy import deepcopy
import hashlib
import json

import pytest

from scripts import audit_admission_source_additions as audit


@pytest.fixture
def documents(monkeypatch):
    source = b'# https://example.test/spec\ndef test_a():\n    assert 1 == []\n'
    span = lambda start, end: dict(path='test.py', start_byte=start, end_byte=end)
    predicate = span(source.index(b'1 == []'), source.index(b'1 == []') + 7)
    fact = dict(check_id='Q0', predicate_span=predicate, predicate='1 == []',
                implies_test_invalid=False, operands=[
                    dict(span=span(predicate['start_byte'], predicate['start_byte'] + 1), text='1'),
                    dict(span=span(predicate['end_byte'] - 2, predicate['end_byte']), text='[]')])
    types = dict(premise='conditional', limitation='not validity', facts=[fact],
                 modules={'test.py': dict(source_sha256=hashlib.sha256(source).hexdigest())})
    controls = dict(controls=[], documentation_links=[dict(url='https://example.test/spec',
        span=span(2, 27), fetched=False, normative_status='not_established_by_link_alone')])
    defaults = dict(facts=[], source_hashes={})
    analysis = dict(additional_source_analyses=dict(conditional_types=types,
        recovered_controls=controls, call_defaults=defaults), analysis=dict(
        sources={'S0': dict(path='test.py', start_byte=0)}, obligations={'Q0':
            dict(at=dict(source='S0', start=predicate['start_byte'], end=predicate['end_byte']))}))
    payload = dict(checks={'Q0': {}}, conditional_predicate_facts={
        key: types[key] for key in ('premise', 'limitation', 'facts')},
        source_documentation_links=controls['documentation_links'])
    monkeypatch.setattr(audit, 'source_versions', lambda *_: (
        {'test.py': source}, {'test.py': source}, 'test.py', span(27, len(source))))
    return deepcopy(analysis), deepcopy(payload)


def run(documents):
    analysis, payload = documents
    return audit.verify_additions(dict(prompt=json.dumps(payload)), analysis, {}, {})


def test_exact_conditional_source_and_unfetched_link_pass(documents):
    result = run(documents)
    assert result['conditional_facts'] == result['links'] == 1
    assert result['semantic_validity_not_established_by_provenance_audit']


def test_modified_fact_cannot_reuse_correct_source_hash(documents):
    for facts in (documents[0]['additional_source_analyses']['conditional_types'],
                  documents[1]['conditional_predicate_facts']):
        facts['facts'][0]['predicate'] = '1 != []'
    with pytest.raises(ValueError, match='predicate source mismatch'):
        run(documents)


def test_exact_fact_cannot_be_attached_to_another_check(documents):
    documents[0]['analysis']['obligations']['Q0']['at']['start'] += 1
    with pytest.raises(ValueError, match='indexed check predicate'):
        run(documents)


def test_link_cannot_be_promoted_to_fetched_evidence(documents):
    documents[0]['additional_source_analyses']['recovered_controls']['documentation_links'][0]['fetched'] = True
    documents[1]['source_documentation_links'][0]['fetched'] = True
    with pytest.raises(ValueError, match='promoted to fetched'):
        run(documents)


def test_provider_projection_cannot_omit_limitation(documents):
    del documents[1]['conditional_predicate_facts']['limitation']
    with pytest.raises(ValueError, match='projection mismatch'):
        run(documents)


@pytest.fixture
def original_controls(monkeypatch):
    original = b'def fixture():\n    return api\n\ndef test_root():\n    api(1)\n\ndef test_example():\n    api(2)\n'
    modified = original.replace(b'api(1)', b'api("much longer argument")')
    root_start, root_end = original.index(b'def test_root'), original.index(b'\n\ndef test_example')
    start, end = original.index(b'def test_example'), len(original) - 1
    span = lambda begin, finish, version: dict(path='test.py', start_byte=begin, end_byte=finish, version=version)
    example_start = original.index(b'api(2)')
    changed_start = modified.index(b'api("much longer argument")')
    control = dict(name='test_example', source_version='original', span=span(start, end, 'original'),
        code=original[start:end].decode(), oracle_validity='unconfirmed_source_example', matches=[dict(
            changed_call=span(changed_start, changed_start + len(b'api("much longer argument")'), 'modified'),
            example_call=span(example_start, example_start + 6, 'original'), equivalence_proved=False,
            fixture=dict(source_version='original', span=span(0, original.index(b'\n\ndef test_root'), 'original'),
                         code=original[:original.index(b'\n\ndef test_root')].decode()))])
    controls = dict(controls=[control], documentation_links=[],
        original_source_sha256=hashlib.sha256(original).hexdigest(),
        modified_source_sha256=hashlib.sha256(modified).hexdigest())
    analysis = dict(additional_source_analyses=dict(conditional_types=dict(facts=[]),
        recovered_controls=controls, call_defaults=dict(facts=[], source_hashes={})))
    payload = dict(modified_test=modified[root_start:modified.index(b'\n\ndef test_example')].decode(),
                   recovered_source_controls=[deepcopy(control)])
    monkeypatch.setattr(audit, 'source_versions', lambda *_: ({'test.py': original}, {'test.py': modified},
        'test.py', dict(path='test.py', start_byte=root_start, end_byte=root_end)))
    return analysis, payload


def test_original_controls_survive_modified_source_byte_shift(original_controls):
    assert run(original_controls)['controls'] == 1


@pytest.mark.parametrize('target', ['control', 'example_call', 'fixture'])
def test_original_roles_cannot_point_to_modified_source(original_controls, target):
    analysis, payload = original_controls
    for control in (analysis['additional_source_analyses']['recovered_controls']['controls'][0],
                    payload['recovered_source_controls'][0]):
        span = (control['span'] if target == 'control' else control['matches'][0]['fixture']['span']
                if target == 'fixture' else control['matches'][0]['example_call'])
        span['version'] = 'modified'
    with pytest.raises(ValueError, match='original source|source versions missing'):
        run(original_controls)
