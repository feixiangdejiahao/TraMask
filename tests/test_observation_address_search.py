"""Generic constructive-search fixtures, independent of benchmark outcomes."""
import hashlib
import json

import pytest

from anchor_retrieval.syntax import Source
from prototypes.observation_address_search import SearchBudget,generate
from generic_composition.emitter import emit
from relational_gap.frontend import extract_frontend,to_emitter_corpus
from tests.test_observation_address_join import GO,TS,SETUP,source


def prepare(code=None,language='python',files=None,budget=None):
    files=files or [Source({'python':'test_search.py','go':'search_test.go','typescript':'search.test.ts'}[language],code or source(),language)]
    frontend=extract_frontend(files);corpus=to_emitter_corpus(frontend)
    return corpus,frontend,{mode:generate(corpus,frontend,mode=mode,budget=budget) for mode in ('address','receiver_only')}


def targets(result):
    return [c for c in result['candidates'] if c['base_test_id'].endswith(':test_target') or c['base_test_id'].endswith(':TestTarget') or 'target' in c['base_test_id']]


def test_full_bank_is_shared_and_owner_field_lookup_precedes_pair_budget():
    _,_,results=prepare(source(donor='box.put_other("a",9)\nbox.put("a",1)'),budget=SearchBudget(max_candidates=16,max_attempts=1))
    a,b=results['address'],results['receiver_only']
    assert a['full_source_bank_sha256']==b['full_source_bank_sha256']
    assert a['demand_population_sha256']==b['demand_population_sha256']
    assert len(a['full_source_bank'])==2
    assert a['raw_retrieved_count']==2 and b['raw_retrieved_count']==4
    assert all(len(q['all_hit_ids'])==1 for q in a['queries'])
    assert all(len(q['all_hit_ids'])==2 for q in b['queries'])
    assert 'put("a",1)' in a['candidates'][0]['edits'][0]['after']
    assert 'put_other("a",9)' in b['candidates'][0]['edits'][0]['after']
    assert a['attempts']==b['attempts']==1


def test_donor_without_receiver_observation_can_supply_a_source_action():
    code=source().replace('assert box.get("a")==1','assert True')
    _,_,results=prepare(code)
    assert results['address']['full_source_bank_count']==1
    assert targets(results['address'])[0]['edits'][0]['after'].strip()=='box.put("b",1)'


def test_cross_file_different_constructor_calls_unify_same_declaration_owner():
    common=Source('store.py',SETUP+'\ndef build(): return Store()\n','python')
    donor=Source('test_donor.py','from store import build\ndef test_donor():\n    original=build()\n    original.put("a",1)\n    assert True\n','python')
    recipient=Source('test_target.py','from store import Store\ndef test_target():\n    recipient=Store()\n    assert recipient.get("b")==0\n','python')
    corpus,_,results=prepare(files=[common,donor,recipient])
    candidates=targets(results['address']);assert candidates,results['address']
    c=candidates[0]
    assert c['edits'][0]['after'].strip()=='recipient.put("b",1)'
    assert c['provenance']['source_action']['path']=='test_donor.py'
    assert c['provenance']['insertion_statement']['path']=='test_target.py'
    assert not emit(corpus,candidates)['unsupported']


def test_later_irrelevant_control_does_not_erase_prior_closed_donor_action():
    code=source().replace('assert box.get("a")==1','if flag:\n        external()\n    assert True')
    _,_,results=prepare(code)
    assert targets(results['address'])


def test_action_inside_branch_is_not_promoted_to_unconditional_donor():
    code=source().replace('    box.put("a",1)','    if flag:\n        box.put("a",1)').replace('assert box.get("a")==1','assert True')
    _,_,results=prepare(code)
    assert results['address']['full_source_bank_count']==0
    assert not targets(results['address'])


def test_source_global_owner_lookup_does_not_equate_same_named_other_class():
    other='''class Other:
    def __init__(self): self.items={}
    def put(self,k,v): self.items[k]=v
'''
    code=source(donor='box=Other()\nbox.put("a",1)',setup=SETUP+other).replace('assert box.get("a")==1','assert True')
    _,_,results=prepare(code)
    assert results['address']['full_source_bank_count']==1
    assert not targets(results['address'])
    assert results['address']['raw_retrieved_count']==0


def test_no_per_query_truncation_before_global_pair_budget():
    actions='\n'.join(f'box.put("a",{i})' for i in range(40))
    _,_,results=prepare(source(donor=actions),budget=SearchBudget(max_candidates=2,max_attempts=128))
    r=results['address']
    assert r['full_source_bank_count']==40
    assert all(len(q['all_hit_ids'])==40==len(q['retrieved_ids']) for q in r['queries'])
    assert r['scheduled_pair_count']==80
    assert len(r['candidates'])==2


def test_lookup_receipts_independently_recompute_from_full_bank():
    _,_,results=prepare(source(donor='box.put_other("a",9)\nbox.put("a",1)'))
    for mode,r in results.items():
        for q in r['queries']:
            expected=[b['id'] for b in r['full_source_bank'] if b['owner_key']==q['owner_key'] and (mode=='receiver_only' or q['field'] in b['fields'])]
            assert q['all_hit_ids']==q['retrieved_ids']==expected
        assert r['attempted_pairs']==r['scheduled_pairs'][:r['attempts']]
        assert r['attempts']==len(r['candidates'])+sum(r['pair_skipped'].values())


def test_literal_alias_index_refs_point_to_actual_literal_source():
    setup=SETUP.replace('def get(self,k): return self.items[k]','def get(self,k):\n        chosen="b"\n        return self.items[chosen]')
    corpus,_,results=prepare(source(setup=setup))
    candidate=targets(results['address'])[0]
    at=candidate['provenance']['key_substitution']['demand_actual']
    raw=corpus['sources'][at['path']]['code'].encode()
    assert raw[at['start_byte']:at['end_byte']].decode()=='"b"'
    assert candidate['edits'][0]['after'].strip()=='box.put("b",1)'
    assert candidate['provenance']['read_effect']['key_span']!=at


def test_observation_phase_still_precedes_saved_read_before_rebinding():
    corpus,_,results=prepare(source(target='key="b"\nvalue=box.get(key)\nkey="a"\nassert value==0'))
    candidate=targets(results['address'])[0];at=candidate['edits'][0]['span']['start_byte']
    assert corpus['sources']['test_search.py']['code'].encode()[at:].startswith(b'value=box.get(key)')
    assert candidate['edits'][0]['after'].strip()=='box.put(key,1)'


def test_source_bank_rejects_unknown_argument_dependencies_without_guessing():
    _,_,results=prepare(source(donor='box.put("a",compute())'))
    assert results['address']['full_source_bank_count']==0
    assert results['address']['bank_skipped'].get('nonliteral_operation_argument')


@pytest.mark.parametrize('language,code',[('go',GO),('typescript',TS)])
def test_same_constructive_join_supports_existing_go_and_typescript_syntax(language,code):
    corpus,_,results=prepare(code,language)
    candidates=targets(results['address']);assert candidates,results['address']
    assert '"b",1' in candidates[0]['edits'][0]['after']
    assert not emit(corpus,candidates[:1])['unsupported']


def test_repeated_source_runs_preserve_candidates_bank_and_queries_except_timings():
    corpus,frontend,results=prepare()
    again=generate(corpus,frontend)
    first=results['address'];first.pop('timings');again.pop('timings')
    assert first==again


def test_invalid_global_budget_is_rejected():
    corpus,frontend,_=prepare()
    with pytest.raises(ValueError):generate(corpus,frontend,budget=SearchBudget(max_attempts=0))
