"""Fixed source-structural sampling and paired input identity."""
import copy
import hashlib
import json

import pytest

from anchor_retrieval.syntax import Source
from prototypes.finite_oracle_questions import build_question
from relational_gap.frontend import extract_frontend,to_emitter_corpus
from relational_gap.provider import encoded
from scripts.prepare_finite_oracle_pairs import choose_family,provider_encoded,verify_pair,wire_preview


def family(identifier,members,editable=True):
    return dict(id=identifier,status='factorized',variants=[dict(candidate_id=member,
        assertions=[dict(editable=editable)]) for member in members])


def test_multi_member_priority_is_structural_and_order_invariant():
    rows=[family('single',['only']),family('group_a',['x','y']),family('group_b',['a','b','c','d','e'])]
    expected=min(rows[1:],key=lambda r:hashlib.sha256(r['id'].encode()).hexdigest())
    forward=choose_family(dict(families=rows))
    reverse=choose_family(dict(families=list(reversed(copy.deepcopy(rows)))))
    assert forward==reverse
    assert forward[0]['id']==expected['id']
    members=sorted(expected['variants'],key=lambda v:hashlib.sha256(v['candidate_id'].encode()).hexdigest())[:4]
    assert forward[1]==members


def test_uneditable_families_do_not_replace_explicit_singleton_fallback():
    chosen,members,info=choose_family(dict(families=[family('bad',['x','y'],False),family('single',['ok'])]))
    assert chosen['id']=='single' and len(members)==1
    assert info['selection']=='sha_first_eligible_singleton_fallback'
    chosen,members,info=choose_family(dict(families=[family('bad',['x','y'],False)]))
    assert chosen is None and members==[] and info['selection']=='no_eligible_family'


def paired():
    code='def test_sample():\n    name = "你好"\n    value = operation(2)\n    assert value == 4\n'
    front=extract_frontend([Source('test_sample.py',code,'python')]);corpus=to_emitter_corpus(front)
    base=next(iter(corpus['tests']));start=code.encode().index(b'operation(2)')+len(b'operation(')
    candidates=[dict(id=str(i),base_test_id=base,imports=[],edits=[dict(
        span=dict(path='test_sample.py',start_byte=start,end_byte=start+1),before='2',after=str(i))]) for i in [2,3]]
    requests=[build_question(corpus,front,candidates,'Double the argument.',representation=arm) for arm in ['template','expanded']]
    for request in requests: request['source_prepared']='/tmp/frozen_source'
    return requests


def test_pair_reconstructs_unicode_members_and_exact_provider_preview():
    a,b=paired();common,identity=verify_pair(a,b)
    assert identity['all_common_fields_equal'] and len(identity['member_roundtrips'])==2
    assert len(common['variants'])==2
    wire=wire_preview(a)
    assert provider_encoded(wire)==encoded(wire)
    assert json.loads(provider_encoded(wire))==wire


@pytest.mark.parametrize('mutation',['contract','source','member'])
def test_pair_rejects_treatment_information_or_source_change(mutation):
    a,b=paired();b=copy.deepcopy(b)
    payload=json.loads(b['prompt'])
    if mutation=='contract': payload['issue']='A different required behavior.'
    elif mutation=='source': payload['test_source'][0]['modified_test']+='\n    assert True\n'
    else: b['finite_members'].reverse()
    b['prompt']=json.dumps(payload)
    with pytest.raises(ValueError): verify_pair(a,b)
