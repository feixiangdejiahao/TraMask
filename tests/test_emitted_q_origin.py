"""Origin is proved from exact emitted clones and edits, not assertion similarity."""
import ast
import sys
import types

import pytest

from anchor_retrieval.syntax import Source
from experimental.assertion_write_origin import Module
from experimental.emitted_q_origin import clone_mapping,map_span,bind_plan_origins
from experimental.observed_write_runtime import Observer,build_plan,instrument_sources
from generic_composition.emitter import emit
from relational_gap.frontend import extract_frontend,to_emitter_corpus


LIB='''class Item:
    def __init__(self, value):
        self.flag = value
'''
TEST='''from lib import Item
def test_value():
    item = Item(False)
    assert item.flag is False
'''


def fixture(edits=()):
    corpus=to_emitter_corpus(extract_frontend([Source('lib.py',LIB,'python'),Source('test_case.py',TEST,'python')]))
    base=next(iter(corpus['tests']))
    candidate=dict(id='candidate',base_test_id=base,source_test_ids=[],imports=[],edits=list(edits))
    emitted=emit(corpus,[candidate])
    sources={**corpus['sources'],**{p:{'code':code} for p,code in emitted['files'].items()}}
    return corpus,candidate,emitted,sources


def edit(before,after,role='input'):
    start=TEST.index(before)
    return dict(span=dict(path='test_case.py',start_byte=start,end_byte=start+len(before)),before=before,after=after,role=role)


def node_in_clone(sources,item,kind):
    module=Module(item['path'],sources[item['path']]['code'],ast.parse(sources[item['path']]['code']))
    function=next(n for n in ast.walk(module.tree) if isinstance(n,ast.FunctionDef) and n.name==item['test_name'])
    node=next(n for n in ast.walk(function) if isinstance(n,kind))
    return module.span(node)


def test_control_and_generated_q_and_allocation_map_to_same_source_with_changed_input():
    corpus,candidate,emitted,sources=fixture([edit('False','True')])
    origins=[]
    for item,change in [(emitted['controls'][0],None),(emitted['obligations'][0],candidate)]:
        mapping=clone_mapping(corpus,sources,item,change)
        q=map_span(mapping,node_in_clone(sources,item,ast.Assert),ast.Assert)
        allocation=map_span(mapping,node_in_clone(sources,item,ast.Call),ast.Call)
        assert q and allocation
        origins.append((q['span'],allocation['span']))
    assert origins[0]==origins[1]
    assert origins[0][0]['line']==4


def test_expected_replacement_retains_q_origin_but_records_assertion_change():
    before='assert item.flag is False'
    corpus,candidate,emitted,sources=fixture([edit(before,'assert item.flag is True','semantic_expected')])
    item=emitted['obligations'][0]
    mapping=clone_mapping(corpus,sources,item,candidate)
    origin=map_span(mapping,node_in_clone(sources,item,ast.Assert),ast.Assert)
    assert origin['source_node_edited']
    assert origin['edit_roles']==['semantic_expected']
    assert origin['span']['line']==4


def test_inserted_identical_assertion_is_not_given_the_existing_q_origin():
    before='assert item.flag is False'
    corpus,candidate,emitted,sources=fixture([edit(before,before+'\n    '+before)])
    item=emitted['obligations'][0]
    module=Module(item['path'],sources[item['path']]['code'],ast.parse(sources[item['path']]['code']))
    function=next(n for n in ast.walk(module.tree) if isinstance(n,ast.FunctionDef) and n.name==item['test_name'])
    mapping=clone_mapping(corpus,sources,item,candidate)
    assertions=[n for n in ast.walk(function) if isinstance(n,ast.Assert)]
    assert len(assertions)==2
    assert all(map_span(mapping,module.span(node),ast.Assert) is None for node in assertions)


def test_runtime_probe_insertion_does_not_break_unchanged_q_origin():
    at=TEST.index('assert')
    probe=dict(span=dict(path='test_case.py',start_byte=at,end_byte=at),before='',
               after='pass\n    ',role='runtime_probe')
    corpus,candidate,emitted,sources=fixture([probe])
    item=emitted['obligations'][0]
    mapping=clone_mapping(corpus,sources,item,candidate)
    assert map_span(mapping,node_in_clone(sources,item,ast.Assert),ast.Assert)['span']['line']==4


def test_plan_drops_unmappable_replacement_instead_of_manufacturing_comparability():
    before='assert item.flag is False'
    corpus,candidate,emitted,sources=fixture([edit(before,before+'\n    '+before)])
    item=emitted['obligations'][0]
    plan=build_plan(sources,assertion_functions={item['path']:[item['test_name']]})
    assert len(plan['queries'])==2
    mapped=bind_plan_origins(plan,corpus,sources,[item],[candidate])
    assert mapped['queries']==[] and mapped['writes']==[]
    assert mapped['source_q_mapping']['queries_excluded']==2


def test_exact_clone_mismatch_is_rejected_before_any_mapping():
    corpus,candidate,emitted,sources=fixture()
    item=emitted['obligations'][0]
    sources[item['path']]['code']=sources[item['path']]['code'].replace(item['test_name'],item['test_name']+'_tampered')
    plan=build_plan(sources,assertion_paths=[item['path']])
    mapped=bind_plan_origins(plan,corpus,sources,[item],[candidate])
    assert mapped['queries']==[]
    assert mapped['source_q_mapping']['clone_failures'][0]['reason']=='emitted_clone_not_uniquely_equal_to_recorded_edits'


def test_real_control_and_generated_events_share_proven_source_q_and_allocation(monkeypatch):
    corpus,candidate,emitted,sources=fixture([edit('False','True')])
    items=[emitted['controls'][0],emitted['obligations'][0]]
    plan=build_plan(sources,assertion_functions={'test_case.py':[row['test_name'] for row in items]})
    plan=bind_plan_origins(plan,corpus,sources,items,[candidate])
    assert plan['source_q_mapping']['queries_mapped']==2
    overlays=instrument_sources(sources,plan,runtime_module='_mapped_observer')
    observer=Observer()
    monkeypatch.setitem(sys.modules,'_mapped_observer',types.SimpleNamespace(observer=observer))
    modules={}
    for path in ['lib.py','test_case.py']:
        module=types.ModuleType(path[:-3]);monkeypatch.setitem(sys.modules,path[:-3],module)
        exec(compile(overlays[path],path,'exec'),module.__dict__);modules[path]=module
    getattr(modules['test_case.py'],items[0]['test_name'])()
    with pytest.raises(AssertionError):
        getattr(modules['test_case.py'],items[1]['test_name'])()
    a,b=[row for row in observer.events if row['kind']=='assertion_read']
    assert a['q_span']!=b['q_span']
    assert a['source_q_span']==b['source_q_span']
    assert a['source_allocation_span']==b['source_allocation_span']
    assert a['source_last_observed_writer']==b['source_last_observed_writer']
    assert a['value']['value'] is False and b['value']['value'] is True
