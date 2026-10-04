import copy
import json

import pytest

from anchor_retrieval.syntax import Source
from relational_gap.frontend import extract_frontend, to_emitter_corpus
from relation_search import atomic_contract_gap_proposals as atomic
from relation_search import contract_gap_proposals as core


def fixture(count=4):
    code = 'from api import double\n' + '\n'.join(
        f'def test_value_{i}():\n    assert double(3) == 6\n' for i in range(count))
    frontend = extract_frontend([Source('test_value.py',code,'python','repository'),
        Source('api.py','def double(n):\n    """Return twice n."""\n    return n*2\n','python','repository')])
    corpus = to_emitter_corpus(frontend)
    return corpus,frontend,core.prepare(corpus,frontend,'double returns twice its input.')


def answer(slot, replacement='double(4) == 8'):
    payload=json.loads(slot['request']['prompt']);seed=payload['seeds'][0]
    return json.dumps({'tests':[{'seed_alias':seed['seed_alias'],
        'rewritten_test':seed['context']['original_test'].replace('double(3) == 6',replacement)}]})


def test_single_context_and_catalog_are_exact_no_retrieval_or_mutation():
    _,_,previous=fixture();before=copy.deepcopy(previous)
    for rank in (1,2,3):
        slot=atomic.prepare_slot(previous,rank)
        p=json.loads(slot['request']['prompt']);old=json.loads(previous['request']['prompt'])
        assert p['seeds']==[old['seeds'][rank-1]]
        assert p['issue_api_catalog']==old['issue_api_catalog'] and p['issue']==old['issue']
        assert p['response_schema']['properties']['tests']['maxItems']==1
        assert slot['request']['prompt_bytes']==len(slot['request']['system'].encode())+len(slot['request']['prompt'].encode())
        assert slot['request']['id']==core._identity(slot['request'])
    assert previous==before and core.MAX_PROPOSALS==3


def test_missing_anchor_remains_empty_and_does_not_recover_omitted_or_repeat():
    _,_,previous=fixture(1)
    previous['omitted'].append({'seed_alias':'S2','reason':'whole_context_prompt_budget'})
    assert atomic.prepare_slot(previous,1)['request']
    for rank in (2,3):
        result=atomic.prepare_slot(previous,rank)
        assert result['status']=='no_anchor' and result['request'] is None


@pytest.mark.parametrize('fault',['two_tests','length','format','escape','scope'])
def test_original_decoder_preserves_unknown_and_boundary_failures(fault):
    corpus,frontend,previous=fixture();slot=atomic.prepare_slot(previous,2)
    content=answer(slot)
    if fault=='two_tests':
        value=json.loads(content);value['tests']*=2;content=json.dumps(value)
    elif fault=='format':content='{"tests":'
    elif fault=='escape':
        value=json.loads(content);value['tests'][0]['rewritten_test']+='\ndef test_extra():\n    assert False';content=json.dumps(value)
    elif fault=='scope':content=answer(slot,'eval("8") == 8')
    result=atomic.decide(corpus,frontend,slot,content,finish_reason='length' if fault=='length' else 'stop')
    assert result['candidates']==[]
    assert result['status']=='unknown' if fault in {'two_tests','length','format'} else result['rejected']
    assert core.MAX_PROPOSALS==3


def test_slot_rank_and_complete_duplicate_ledger_keep_earliest():
    corpus,frontend,previous=fixture();slot=atomic.prepare_slot(previous,1)
    d=atomic.decide(corpus,frontend,slot,answer(slot));assert d['candidates'][0]['order']==[1]
    later=copy.deepcopy(d);later['candidates'][0]['order']=[3]
    rows=[dict(slot=1,decoded=d,decoded_receipt={},preparation_status='prepared'),
          dict(slot=2,decoded={'status':'unknown','reason':'generation_not_prepared','candidates':[]},decoded_receipt={},preparation_status='no_anchor'),
          dict(slot=3,decoded=later,decoded_receipt={},preparation_status='prepared')]
    aggregate=atomic.aggregate(rows)
    assert [p['order'] for p in aggregate['candidates']]==[[1]]
    assert [row['disposition'] for row in aggregate['slot_ledger']]==['candidate','no_anchor','duplicate']
    assert aggregate['slot_ledger'][2]['duplicate_of_slot']==1


def test_tampered_complete_anchor_refuses_preparation():
    _,_,previous=fixture();payload=json.loads(previous['request']['prompt'])
    payload['seeds'][0]['context']['original_test']+=' changed'
    previous['request']['prompt']=json.dumps(payload)
    previous['request']['id']=core._identity(previous['request'])
    with pytest.raises(ValueError,match='context_changed'):atomic.prepare_slot(previous,1)
