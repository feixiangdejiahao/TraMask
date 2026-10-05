import copy
import json

import pytest

from anchor_retrieval.syntax import Source
from relational_gap.frontend import extract_frontend, to_emitter_corpus
from relation_search import omitted_anchor_proposals as relation
from relation_search import contract_gap_proposals as core
from relation_search import oracle


def fixture(count=4):
    code='from api import double\n'+'\n'.join(f'def test_value_{i}():\n    # 完整源断言\n    assert double(3) == 6\n' for i in range(count))
    frontend=extract_frontend([Source('test_value.py',code,'python','repository'),
        Source('api.py','def double(n):\n    """Return twice n."""\n    return n*2\n','python','repository')])
    corpus=to_emitter_corpus(frontend);issue='double returns twice its input.'
    full=core.prepare(corpus,frontend,issue);payload=json.loads(full['request']['prompt']);payload['seeds']=payload['seeds'][:1]
    budget=len(full['request']['system'].encode())+len(json.dumps(payload,ensure_ascii=False,separators=(',',':')).encode())
    inherited=core.prepare(corpus,frontend,issue,max_prompt_bytes=budget)
    assert len(inherited['seeds'])==1 and len(inherited['omitted'])==count-1
    return corpus,frontend,issue,inherited


def answer(slot):
    seed=json.loads(slot['request']['prompt'])['seeds'][0]
    return json.dumps(dict(tests=[dict(seed_alias=seed['seed_alias'],rewritten_test=seed['context']['original_test'].replace('double(3) == 6','double(4) == 8'))]))


def test_rebuilds_all_original_omissions_in_order_complete_utf8_context():
    corpus,frontend,issue,inherited=fixture();before=copy.deepcopy(inherited)
    recovered=relation.recover(corpus,frontend,issue,inherited)
    assert [r['original_omission'] for r in recovered['recovered']]==inherited['omitted']
    old=json.loads(inherited['request']['prompt'])
    for rank,row in enumerate(recovered['recovered'],1):
        slot=relation.prepare_slot(recovered,rank);payload=json.loads(slot['request']['prompt']);seed=slot['seeds'][0]
        assert seed['base_test_id']==inherited['omitted'][rank-1]['base_test_id']
        source,test,_=core._source_test(corpus,seed['base_test_id'])
        assert payload['seeds'][0]['context']['original_test']==source.data[test['span']['start_byte']:test['span']['end_byte']].decode()
        assert payload['issue_api_catalog']==old['issue_api_catalog'] and payload['issue']==old['issue']
        assert slot['slot']==payload['generation_slot']==rank
        assert slot['request']['reasoning_effort']=='low' and slot['request']['max_tokens']==16384
        assert slot['request']['prompt_bytes']==len(slot['request']['system'].encode())+len(slot['request']['prompt'].encode())
        assert slot['request']['id']==core._identity(slot['request'])
    assert inherited==before and core.MAX_SEEDS==4


def test_provenance_is_attached_before_semantic_gate_without_changing_complete_program():
    corpus,frontend,issue,inherited=fixture();recovered=relation.recover(corpus,frontend,issue,inherited)
    slot=relation.prepare_slot(recovered,2);decoded=relation.decide(corpus,frontend,slot,answer(slot))
    candidate=decoded['candidates'][0]
    assert candidate['order']==[2] and candidate['source_provenance']['seed']==inherited['omitted'][1]['base_test_id']
    assert oracle.preview(corpus,candidate)==json.loads(answer(slot))['tests'][0]['rewritten_test']
    assert decoded['semantic_validity']=='unconfirmed' and not decoded['alarm_eligible']
    assert len(candidate['edits'])==1 and candidate['edits'][0]['role']=='program'


@pytest.mark.parametrize('fault',['omission_order','source','original_test','catalog','anchor'])
def test_recovery_rejects_changed_origin_context_or_selection(fault):
    corpus,frontend,issue,inherited=fixture();recovered=relation.recover(corpus,frontend,issue,inherited)
    if fault=='omission_order':recovered['recovered'].reverse()
    elif fault=='source':recovered['source_sha256']={}
    elif fault=='anchor':recovered['recovered'][0]['preparation']['seeds'][0]['base_test_id']=inherited['seeds'][0]['base_test_id']
    else:
        prepared=recovered['recovered'][0]['preparation'];payload=json.loads(prepared['request']['prompt'])
        if fault=='catalog':payload['issue_api_catalog']={}
        else:payload['seeds'][0]['context']['original_test']+='\n# changed'
        prepared['request']['prompt']=json.dumps(payload,ensure_ascii=False,separators=(',',':'))
        prepared['request']['id']=core._identity(prepared['request'])
    with pytest.raises(ValueError):relation.validate_recovery(corpus,inherited,recovered)


def test_empty_and_nonbudget_omissions_do_not_refill_visible_anchors():
    corpus,frontend,issue,inherited=fixture(1);inherited['omitted'].append(dict(base_test_id='unbound',reason='identity_context_unknown'))
    recovered=relation.recover(corpus,frontend,issue,inherited)
    assert recovered['recovered']==[]
    assert all(relation.prepare_slot(recovered,slot)['status']=='no_anchor' for slot in (1,2,3))


def test_duplicate_or_visible_omission_fails_closed():
    _,_,_,inherited=fixture();inherited['omitted'][1]=inherited['omitted'][0]
    with pytest.raises(ValueError):relation.omissions(inherited)
    inherited['omitted']=[dict(inherited['seeds'][0],reason='whole_context_prompt_budget')]
    with pytest.raises(ValueError):relation.omissions(inherited)


@pytest.mark.parametrize('fault',['length','format','escape','multiple'])
def test_decoder_keeps_unknown_refusal_and_complete_body_boundaries(fault):
    corpus,frontend,issue,inherited=fixture();slot=relation.prepare_slot(relation.recover(corpus,frontend,issue,inherited),1)
    content=answer(slot)
    if fault=='format':content='{"tests":'
    elif fault in {'escape','multiple'}:
        value=json.loads(content)
        if fault=='escape':value['tests'][0]['rewritten_test']+='\ndef test_other():\n    assert False'
        else:value['tests']*=2
        content=json.dumps(value)
    decoded=relation.decide(corpus,frontend,slot,content,finish_reason='length' if fault=='length' else 'stop')
    assert decoded['candidates']==[]


@pytest.mark.parametrize('language',['go','typescript'])
def test_nonpython_omitted_anchor_keeps_registration_and_provenance(language):
    import test_contract_gap_proposals as fixtures
    path,code,api=fixtures.SAMPLES[language]
    if language=='go':
        code+='\nfunc TestOther(t *testing.T) { if double(3) != 6 { t.Fatal("wrong") } }\n'
    else:code+='\nit("other", () => { expect(double(3)).toBe(6); });\n'
    corpus,frontend=fixtures.fixture(language,code);issue='double returns twice its input.'
    full=core.prepare(corpus,frontend,issue);payload=json.loads(full['request']['prompt']);payload['seeds']=payload['seeds'][:1]
    budget=len(full['request']['system'].encode())+len(json.dumps(payload,ensure_ascii=False,separators=(',',':')).encode())
    inherited=core.prepare(corpus,frontend,issue,max_prompt_bytes=budget)
    assert len(inherited['omitted'])==1
    slot=relation.prepare_slot(relation.recover(corpus,frontend,issue,inherited),1)
    context=json.loads(slot['request']['prompt'])['seeds'][0]
    rewritten=context['context']['original_test'].replace('double(3)','double(4)').replace('!= 6','!= 8').replace('toBe(6)','toBe(8)')
    decoded=relation.decide(corpus,frontend,slot,json.dumps(dict(tests=[dict(seed_alias=context['seed_alias'],rewritten_test=rewritten)])))
    assert len(decoded['candidates'])==1
    assert oracle.preview(corpus,decoded['candidates'][0])==rewritten
    assert decoded['candidates'][0]['source_provenance']['seed']==inherited['omitted'][0]['base_test_id']
