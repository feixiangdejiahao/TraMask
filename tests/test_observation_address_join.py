"""Authored generic fixtures; no benchmark truth, model calls or subject runs."""
from copy import deepcopy

import pytest

from anchor_retrieval.syntax import Source
from prototypes.observation_address_join import JoinBudget,generate
from generic_composition.emitter import emit
from relational_gap.frontend import extract_frontend,to_emitter_corpus

SETUP='''objects=[]
class Store:
    def __init__(self):
        self.items={"b":0}
        self.other={}
        objects.append(self)
    def put(self,k,v): self.items[k]=v
    def put_other(self,k,v): self.other[k]=v
    def get(self,k): return self.items[k]
'''


def source(donor='box.put("a",1)',target='assert box.get("b")==0',setup=SETUP):
    return setup+'\ndef test_donor():\n    box=Store()\n    '+donor.replace('\n','\n    ')+'\n    assert box.get("a")==1\n\ndef test_target():\n    box=Store()\n    '+target.replace('\n','\n    ')+'\n'


def prepare(code=None,language='python',budget=None):
    path={'python':'test_addresses.py','go':'addresses_test.go','typescript':'addresses.test.ts'}[language]
    frontend=extract_frontend([Source(path,code or source(),language)])
    corpus=to_emitter_corpus(frontend)
    return corpus,frontend,{mode:generate(corpus,frontend,mode=mode,budget=budget) for mode in ('receiver_only','address')}


def target(rows,source_fragment=None):
    items=[c for c in rows['candidates'] if c['base_test_id'].endswith(':test_target') or c['base_test_id'].endswith(':TestTarget') or 'target' in c['base_test_id']]
    return [c for c in items if source_fragment is None or source_fragment in c['edits'][0]['after']]


def native_fixture(corpus,candidate,*,new_oracle=False,buggy=False):
    """Execute only this authored fixture; oracle changes are explicit here."""
    emitted=emit(corpus,[candidate]);assert not emitted['unsupported']
    code=next(iter(emitted['files'].values()))
    if new_oracle:code=code.replace('assert box.get("b")==0','assert box.get("b")==1')
    if buggy:code=code.replace('self.items[k]=v','self.items.setdefault(k,v)')
    namespace={};exec(compile(code,'<authored-address-fixture>','exec'),namespace)
    failed=False
    try:namespace[emitted['obligations'][0]['test_name']]()
    except AssertionError:failed=True
    return namespace['objects'][-1].items['b'],failed


def test_address_unification_edits_receiver_and_key_before_materialization():
    corpus,frontend,results=prepare();original=deepcopy(corpus)
    baseline=target(results['receiver_only'])[0];joined=target(results['address'])[0]
    assert baseline['edits'][0]['after'].strip()=='box.put("a",1)'
    assert joined['edits'][0]['after'].strip()=='box.put("b",1)'
    proof=joined['provenance']
    assert proof['key_substitution']['formal']=='k'
    assert proof['key_substitution']['old_value']=='a' and proof['key_substitution']['new_value']=='b'
    assert proof['read_effect']['field']==proof['write_effects'][0]['field']=='items'
    assert not proof['assertions_edited'] and not proof['expected_values_inferred']
    assert joined['oracle']['applicability'].startswith('unknown')
    assert corpus==original
    assert results['receiver_only']['action_bank_sha256']==results['address']['action_bank_sha256']
    assert results['receiver_only']['pair_schedule_sha256']==results['address']['pair_schedule_sha256']
    assert generate(corpus,frontend)==results['address']


def test_authored_overwrite_bug_requires_a_separate_justified_new_oracle():
    corpus,_,results=prepare()
    old=target(results['receiver_only'])[0];new=target(results['address'])[0]
    assert native_fixture(corpus,old)==(0,False)
    assert native_fixture(corpus,new)==(1,True)  # retained old oracle is invalid
    assert native_fixture(corpus,new,new_oracle=True)==(1,False)
    assert native_fixture(corpus,new,new_oracle=True,buggy=True)==(0,True)
    assert native_fixture(corpus,old,new_oracle=True)==(0,True)
    assert native_fixture(corpus,old,new_oracle=True,buggy=True)==(0,True)


def test_renamed_methods_fields_parameters_and_receiver_are_not_special_rules():
    code=source().replace('Store','Cabinet').replace('items','entries').replace('put','record').replace('def get(', 'def lookup(').replace('.get(', '.lookup(').replace('box','cabinet').replace('self,k,v','self,index,value').replace('[k]=v','[index]=value').replace('self,k)','self,index)').replace('[k]','[index]')
    _,_,results=prepare(code)
    assert target(results['address'])[0]['edits'][0]['after'].strip()=='cabinet.record("b",1)'


def test_other_field_action_is_in_same_bank_but_pruned_by_address_join():
    _,_,results=prepare(source(donor='box.put("a",1)\nbox.put_other("a",9)'))
    assert len(target(results['receiver_only']))==2
    assert len(target(results['address']))==1
    assert results['address']['skipped']['write_address_missing_or_ambiguous']
    assert results['receiver_only']['action_bank_sha256']==results['address']['action_bank_sha256']


def test_phase_snapshot_uses_read_time_key_before_later_rebinding():
    code=source(target='key="b"\nvalue=box.get(key)\nkey="a"\nassert value==0')
    corpus,_,results=prepare(code)
    joined=target(results['address'])[0]
    assert joined['edits'][0]['after'].strip()=='box.put(key,1)'
    assert joined['provenance']['key_substitution']['new_value']=='b'
    at=joined['edits'][0]['span']['start_byte'];raw=corpus['sources']['test_addresses.py']['code'].encode()
    assert raw[at:].startswith(b'value=box.get(key)')


def test_receiver_alias_and_later_reassignment_preserve_observation_origin():
    code=source(target='alias=box\nvalue=alias.get("b")\nbox=Store()\nassert value==0')
    corpus,_,results=prepare(code)
    joined=target(results['address'])[0]
    assert joined['edits'][0]['after'].strip()=='alias.put("b",1)'
    at=joined['edits'][0]['span']['start_byte']
    assert corpus['sources']['test_addresses.py']['code'].encode()[at:].startswith(b'value=alias.get')


def test_donor_rebinding_does_not_reuse_actions_on_previous_object():
    _,_,results=prepare(source(donor='box.put("a",1)\nbox=Store()'))
    assert not results['address']['candidates']
    assert results['address']['action_bank_count']==0


def test_action_is_inserted_after_prior_overwrite_before_captured_observation():
    code=source(target='box.put("b",3)\nvalue=box.get("b")\nbox.put("b",4)\nassert value==3')
    corpus,_,results=prepare(code)
    joined=next(c for c in target(results['address']) if c['edits'][0]['after'].strip()=='box.put("b",1)')
    at=joined['edits'][0]['span']['start_byte'];raw=corpus['sources']['test_addresses.py']['code'].encode()
    assert raw[at:].startswith(b'value=box.get')
    assert b'box.put("b",3)' in raw[:at]
    assert 'later overwrites' in ' '.join(joined['provenance']['unproved'])


def test_unrelated_prior_get_does_not_make_a_constant_assertion_a_demand():
    _,_,results=prepare(source(target='value=box.get("b")\nassert 2==2'))
    assert not target(results['address'])


def test_effectful_read_key_is_explicit_unknown_and_never_evaluated_by_generator():
    code=source(target='assert box.get(next_key())==0')
    _,_,results=prepare(code)
    assert not target(results['address'])
    assert results['address']['skipped']['key_not_closed_primitive']


def test_key_argument_alias_is_not_removed_leaving_unused_go_style_setup():
    _,_,results=prepare(source(donor='key="a"\nbox.put(key,1)'))
    assert target(results['receiver_only'])
    assert not target(results['address'])
    assert results['address']['skipped']['write_actual_not_direct_literal']


@pytest.mark.parametrize('target_body',[
    'if flag:\n    assert box.get("b")==0',
    'with manager():\n    assert box.get("b")==0',
    'callback=lambda: box.get("b")\nassert box.get("b")==0',
])
def test_control_or_nested_root_scope_is_unknown(target_body):
    _,_,results=prepare(source(target=target_body))
    assert not target(results['address'])
    assert results['address']['skipped']['test_scope_not_straight_line']


def test_fixed_literal_write_key_is_a_constraint_not_a_rewrite_location():
    code=source(donor='box.put_fixed(1)',setup=SETUP+'    def put_fixed(self,v): self.items["a"]=v\n')
    _,_,results=prepare(code)
    assert target(results['receiver_only']) and not target(results['address'])
    assert results['address']['skipped']['fixed_write_key_mismatch']


def test_repeated_matching_writes_remain_explicit_ambiguous():
    code=source(setup=SETUP.replace('def put(self,k,v): self.items[k]=v','def put(self,k,v):\n        self.items[k]=v\n        self.items[k]=0'))
    _,_,results=prepare(code)
    assert target(results['receiver_only']) and not target(results['address'])
    assert results['address']['skipped']['write_address_missing_or_ambiguous']


def test_keyword_formal_mapping_and_utf8_source_bytes():
    code=source(donor='box.put(v=1,k="a")',target='assert box.get(k="猫")==0')
    _,_,results=prepare(code)
    joined=target(results['address'])[0]
    assert joined['edits'][0]['after'].strip()=='box.put(v=1,k="猫")'
    assert joined['provenance']['key_substitution']['argument_slot']==1


def test_output_budget_does_not_change_common_bank_or_planned_pair_order():
    _,_,results=prepare(source(donor='box.put_other("a",8)\nbox.put("a",1)'),budget=JoinBudget(max_candidates=1,max_attempts=8,max_actions_per_group=8))
    a,b=results['address'],results['receiver_only']
    assert a['action_bank_sha256']==b['action_bank_sha256']
    assert a['pair_schedule_sha256']==b['pair_schedule_sha256']
    assert len(a['candidates'])==len(b['candidates'])==1
    assert a['attempts']>b['attempts']


def test_invalid_budget_or_mode_is_rejected():
    corpus,frontend,_=prepare()
    with pytest.raises(ValueError):generate(corpus,frontend,budget=JoinBudget(max_attempts=0))
    with pytest.raises(ValueError):generate(corpus,frontend,mode='guess')


GO='''package sample
import "testing"
type Store struct { items map[string]int }
func Make() *Store { return &Store{items:map[string]int{"b":0}} }
func(s *Store) Put(k string,v int) { s.items[k]=v }
func(s *Store) Get(k string) int { return s.items[k] }
func TestDonor(t *testing.T) {
 box:=Make()
 box.Put("a",1)
 value:=box.Get("a")
 if value!=1 { t.Fatal("wrong") }
}
func TestTarget(t *testing.T) {
 box:=Make()
 value:=box.Get("b")
 if value!=0 { t.Fatal("wrong") }
}
'''


def test_go_method_formal_mapping_uses_same_address_constraint():
    corpus,_,results=prepare(GO,'go')
    candidates=target(results['address'])
    assert candidates,results['address']
    assert candidates[0]['edits'][0]['after'].strip()=='box.Put("b",1)'
    assert not emit(corpus,candidates[:1])['unsupported']


TS='''class Store {
 items: Record<string,number> = {b:0};
 put(k:string,v:number) { this.items[k]=v; }
 get(k:string) { return this.items[k]; }
}
test("donor",()=>{
 const box=new Store();
 box.put("a",1);
 expect(box.get("a")).toBe(1);
});
test("target",()=>{
 const box=new Store();
 expect(box.get("b")).toBe(0);
});
'''


def test_typescript_method_formal_mapping_uses_same_address_constraint():
    corpus,_,results=prepare(TS,'typescript')
    candidates=target(results['address'])
    assert candidates,results['address']
    assert 'box.put("b",1)' in candidates[0]['edits'][0]['after']
    assert not emit(corpus,candidates[:1])['unsupported']


def test_go_fixed_rune_and_string_indexes_do_not_unify_by_decoded_text():
    code=GO.replace('map[string]int','map[interface{}]int').replace('Put(k string,v int) { s.items[k]=v }',"Put(v int) { s.items['a']=v }").replace('Get(k string)','Get(k interface{})').replace('box.Put("a",1)','box.Put(1)').replace('box.Get("b")','box.Get("a")')
    _,_,results=prepare(code,'go')
    assert target(results['receiver_only'])
    assert not target(results['address'])
    assert results['address']['pair_skipped']['fixed_write_key_mismatch']
