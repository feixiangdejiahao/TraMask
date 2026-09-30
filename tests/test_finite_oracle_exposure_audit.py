"""Audit exact provider construction and label-free family scheduling."""
from pathlib import Path

import pytest

from scripts.audit_finite_oracle_pair_inputs import production_payload,production_encoding
from scripts.census_finite_oracle_group_exposure import schedule,sha


def test_audit_executes_only_provider_payload_prefix_without_env_or_dispatch():
    source=(Path(__file__).resolve().parents[1]/'relational_gap/provider.py').read_text()
    request=dict(system='all assertions',prompt='你好',thinking='enabled',reasoning_effort='high')
    wire=production_payload(request,source)
    assert wire['model']=='deepseek-v4-flash' and wire['max_tokens']==16384
    assert wire['thinking']=={'type':'enabled'} and wire['reasoning_effort']=='high'
    assert wire['messages'][1]['content']=='你好'
    actual=production_encoding(wire,source)
    altered=production_encoding(wire,source.replace('ensure_ascii=True','ensure_ascii=False'))
    assert actual!=altered and actual.endswith(b'\n')


def test_unknown_provider_prefix_call_is_rejected_instead_of_executed():
    source='''def dispatch(request,output,root):
    output.mkdir()
    thinking = request.get('thinking', 'disabled')
    secret = root.read_text()
    payload = {'messages': []}
    write(output/'request.json',payload)
'''
    with pytest.raises(ValueError,match='non-payload call'):
        production_payload({},source)


def catalogue():
    ids=['a','b','c','d','e','solo']
    families=[dict(id='group',status='factorized',variants=[dict(candidate_id=cid,assertions=[dict(editable=True)]) for cid in ids[:5]]),
              dict(id='single',status='factorized',variants=[dict(candidate_id='solo',assertions=[dict(editable=False)])])]
    return dict(families=families,candidate_info={cid:dict(family_id='single' if cid=='solo' else 'group') for cid in ids})


def test_two_fixed_policies_keep_same_groups_and_do_not_skip_unofferable():
    first=max(['a','b','c','d','e'],key=sha)
    order=[first,*[cid for cid in ['a','b','c','d','e'] if cid!=first],'solo']
    ranking=dict(impact=dict(ranking=[dict(id=cid,rank=i+1,evidence=dict(eligible=cid!='solo')) for i,cid in enumerate(order)]))
    result=schedule(catalogue(),ranking,budget=2)
    a,b=result['arms']['sha_first4'],result['arms']['impact_first4']
    assert a['selected_family_ids']==b['selected_family_ids']==['group','single']
    assert a['selected_member_count']==b['selected_member_count']==5
    assert a['unofferable_selected_groups']==b['unofferable_selected_groups']==1
    assert first not in a['groups'][0]['member_ids'] and first in b['groups'][0]['member_ids']
    assert result['original_singleton_member_count']==2


def test_incomplete_rank_or_membership_is_rejected():
    ranking=dict(impact=dict(ranking=[dict(id='a',rank=1,evidence=dict(eligible=True))]))
    with pytest.raises(ValueError,match='identity mismatch'): schedule(catalogue(),ranking)
