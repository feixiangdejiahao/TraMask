"""The evaluator must reject generator evidence corruption, not mirror it."""
import copy

import pytest

from anchor_retrieval.syntax import Source
from relational_gap.frontend import extract_frontend, to_emitter_corpus
from scripts import audit_finite_oracle_templates as audit


def evidence():
    code = 'def test_seed():\n    label = "你好"\n    value = operation(11)\n    assert value == 11\n'
    frontend = extract_frontend([Source('test_seed.py', code, 'python')])
    corpus = to_emitter_corpus(frontend)
    base = next(iter(corpus['tests']))
    start = code.encode().index(b'11')
    candidate = dict(id='candidate',base_test_id=base,edits=[dict(
        span=dict(path='test_seed.py',start_byte=start,end_byte=start+2),before='11',after='2000')],
        imports=[dict(name='other',module='.other',imported_name='operation')],source_test_ids=[base])
    return corpus, frontend, [candidate]


def test_audit_checks_original_utf8_source_and_complete_inventory():
    result = audit.verify_case(*evidence(),check_reordering=True)
    assert result['status'] == 'verified'
    assert result['input_candidates'] == result['assertion_instances'] == result['exact_relocated_assertions'] == 1


@pytest.mark.parametrize('corruption',['source','assertion','imports'])
def test_independent_audit_rejects_generator_corruption(monkeypatch,corruption):
    builder = audit.build_catalogue

    def corrupted(*args,**kwargs):
        catalogue = copy.deepcopy(builder(*args,**kwargs))
        family = catalogue['families'][0]
        variant = family['variants'][0]
        if corruption == 'source':
            family['segments'][0] = family['segments'][0].replace('你好','bad')
        elif corruption == 'assertion':
            variant['assertions'] = []
        else:
            variant['imports'] = []
        return catalogue

    monkeypatch.setattr(audit,'build_catalogue',corrupted)
    with pytest.raises(ValueError):
        audit.verify_case(*evidence())
