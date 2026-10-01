"""Filesystem source recovery selects explicit lexical dependencies only."""
import copy
import hashlib
import json

import pytest

from anchor_retrieval.syntax import Source
from relational_gap.frontend import extract_frontend, to_emitter_corpus
from relation_search.source_dependencies import enrich_sources
from relation_search.test_preconditions import analyze


def setup(tmp_path,language,files,selected):
    for path,code in files.items():
        target=tmp_path/path
        target.parent.mkdir(parents=True,exist_ok=True)
        target.write_text(code)
    frontend=extract_frontend([Source(path,files[path],language) for path in selected])
    return to_emitter_corpus(frontend),frontend


def test_recover_missing_barrel_and_interface_contract_without_unrelated_files(tmp_path):
    files={
        'tests/example.test.ts':"import {assemble,producer,original} from '../lib'; test('x',()=>{expect(assemble(original(),1)).toBe(1)});",
        'lib/index.ts':"export * from './ops'; export * from './types';",
        'lib/ops.ts':"""import type {Base} from './types';
export function assemble<T extends Base>(value:T,step:number):unknown{return value}
export function producer():{completed:true}{return {completed:true}}
export function original():Base{return {completed:false}}
""",
        'lib/types.ts':'export interface Base {readonly completed:false}',
        'lib/unrelated.ts':'export interface Irrelevant {other:true}',
    }
    c,f=setup(tmp_path,'typescript',files,['tests/example.test.ts','lib/ops.ts'])
    before=json.dumps(c,sort_keys=True)
    enriched,report=enrich_sources(c,f,tmp_path)
    assert {row['path'] for row in report['added']}=={'lib/index.ts','lib/types.ts'}
    assert 'lib/unrelated.ts' not in enriched['sources']
    assert json.dumps(c,sort_keys=True)==before
    for record in report['added']:
        assert record['source_sha256']==hashlib.sha256(files[record['path']].encode()).hexdigest()
    test_id=next(iter(c['tests']))
    path='tests/example.test.ts';start=files[path].index('original()')
    candidate=dict(id='anonymous',base_test_id=test_id,imports=[],edits=[dict(role='input',
        span=dict(path=path,start_byte=start,end_byte=start+len('original()')),before='original()',after='producer()')])
    result=analyze(enriched,f,candidate)
    assert result['status']=='review'
    assert any(row['code']=='declared_literal_property_contradiction' for row in result['findings'])


def test_frozen_source_is_not_replaced_by_different_filesystem_code(tmp_path):
    files={'tests/test_values.py':'from pkg import compute\ndef test_values():\n    assert compute(1)==1\n',
           'pkg/__init__.py':'from .ops import compute\n','pkg/ops.py':'def compute(value):return value\n'}
    c,f=setup(tmp_path,'python',files,['tests/test_values.py','pkg/ops.py'])
    (tmp_path/'pkg/ops.py').write_text('def compute(value):return 999\n')
    frozen=copy.deepcopy(c)
    enriched,_=enrich_sources(c,f,tmp_path)
    assert enriched['sources']['pkg/ops.py']['code']==files['pkg/ops.py']
    assert c==frozen


def test_configured_alias_is_used_and_no_alias_is_invented(tmp_path):
    files={'tests/example.test.ts':"import {Base} from '~/shape';test('x',()=>{expect(1).toBe(1)});",
           'src/shape.ts':'export interface Base {phase:false}'}
    c,f=setup(tmp_path,'typescript',files,['tests/example.test.ts'])
    enriched,_=enrich_sources(c,f,tmp_path)
    assert 'src/shape.ts' not in enriched['sources']
    f=copy.deepcopy(f);f['module_resolution']['aliases']={'~/*':['src/*']}
    enriched,report=enrich_sources(c,f,tmp_path)
    assert [row['path'] for row in report['added']]==['src/shape.ts']


def test_python_package_initializers_and_src_layout(tmp_path):
    files={'tests/test_value.py':'from pkg import Box\ndef test_value():\n    assert 1==1\n',
           'src/pkg/__init__.py':'from .box import Box\n',
           'src/pkg/box.py':'from .types import Contract\nclass Box:pass\n',
           'src/pkg/types.py':'class Contract:pass\n',
           'src/unrelated.py':'class Irrelevant:pass\n'}
    c,f=setup(tmp_path,'python',files,['tests/test_value.py'])
    enriched,report=enrich_sources(c,f,tmp_path)
    assert {row['path'] for row in report['added']}=={'src/pkg/__init__.py','src/pkg/box.py','src/pkg/types.py'}
    assert 'src/unrelated.py' not in enriched['sources']


def test_go_package_scope_requires_same_package_and_skips_other_tests(tmp_path):
    files={'api/value_test.go':'package api\nimport "testing"\nfunc TestValue(t *testing.T){t.Log(1)}\n',
           'api/value.go':'package api\nfunc read()int{return 1}\n',
           'api/types.go':'package api\ntype Value struct {Number int}\n',
           'api/foreign.go':'package foreign\nfunc unrelated(){}\n',
           'api/other_test.go':'package api\nfunc hiddenCandidate(){}\n',
           'unrelated/value.go':'package api\nfunc unrelated(){}\n'}
    c,f=setup(tmp_path,'go',files,['api/value_test.go'])
    enriched,report=enrich_sources(c,f,tmp_path)
    assert {row['path'] for row in report['added']}=={'api/value.go','api/types.go'}
    assert 'api/other_test.go' not in enriched['sources']
    assert 'unrelated/value.go' not in enriched['sources']


def test_go_imported_local_package_follows_module_metadata(tmp_path):
    files={'go.mod':'module example.test/app\n',
           'api/value_test.go':'package api\nimport("testing";"example.test/app/internal/value")\nfunc TestValue(t *testing.T){t.Log(value.Read())}\n',
           'internal/value/read.go':'package value\nfunc Read()int{return 1}\n',
           'other/unrelated.go':'package unrelated\nfunc Other(){}\n'}
    c,f=setup(tmp_path,'go',files,['api/value_test.go'])
    enriched,report=enrich_sources(c,f,tmp_path)
    assert [row['path'] for row in report['added']]==['internal/value/read.go']
    assert 'other/unrelated.go' not in enriched['sources']


def test_budget_and_cycles_are_explicit_and_deterministic(tmp_path):
    files={'tests/example.test.ts':"import {A} from '../a';test('x',()=>{expect(1).toBe(1)});",
           'a.ts':"export * from './b';",'b.ts':"export * from './a';export * from './c';",'c.ts':'export interface A {x:false}'}
    c,f=setup(tmp_path,'typescript',files,['tests/example.test.ts'])
    first,report=enrich_sources(c,f,tmp_path,max_added_files=1)
    assert [row['path'] for row in report['added']]==['a.ts']
    assert report['limits']['budget_exhausted'] is True
    assert enrich_sources(c,f,tmp_path,max_added_files=1)==(first,report)
    _,limited=enrich_sources(c,f,tmp_path,max_depth=1)
    assert limited['limits']['depth_limit_reached'] is True


def test_symlink_cannot_add_source_outside_repository(tmp_path):
    repository=tmp_path/'repository';repository.mkdir()
    files={'tests/example.test.ts':"import {A} from '../outside';test('x',()=>{expect(1).toBe(1)});"}
    c,f=setup(repository,'typescript',files,['tests/example.test.ts'])
    outside=tmp_path/'outside.ts';outside.write_text('export interface A{x:true}')
    (repository/'outside.ts').symlink_to(outside)
    enriched,report=enrich_sources(c,f,repository)
    assert not report['added']
    assert 'outside.ts' not in enriched['sources']


def test_reference_and_hidden_paths_are_not_added(tmp_path):
    files={'tests/example.test.ts':"import {A} from '../hidden_verifier/shape';test('x',()=>{expect(1).toBe(1)});",
           'hidden_verifier/shape.ts':'export interface A{x:true}'}
    c,f=setup(tmp_path,'typescript',files,['tests/example.test.ts'])
    enriched,report=enrich_sources(c,f,tmp_path)
    assert not report['added']
    assert 'hidden_verifier/shape.ts' not in enriched['sources']


def test_generated_import_uses_donor_module_location(tmp_path):
    files={'tests/example.test.ts':"test('x',()=>{expect(1).toBe(1)});",
           'nested/tests/donor.test.ts':"test('x',()=>{expect(1).toBe(1)});",
           'nested/ops.ts':'export function operate(v:number){return v}'}
    c,f=setup(tmp_path,'typescript',files,['tests/example.test.ts','nested/tests/donor.test.ts'])
    test_id=next(tid for tid,row in c['tests'].items() if row['span']['path']=='tests/example.test.ts')
    candidate=dict(id='anonymous',base_test_id=test_id,imports=[dict(name='generated',module='../ops',
        imported_name='operate',source_path='nested/tests/donor.test.ts')])
    _,report=enrich_sources(c,f,tmp_path,[candidate])
    assert [row['path'] for row in report['added']]==['nested/ops.ts']


@pytest.mark.parametrize('kwargs',[{'max_added_files':-1},{'max_depth':-1},{'max_added_files':True}])
def test_invalid_budget_rejected(tmp_path,kwargs):
    c,f=setup(tmp_path,'python',{'tests/test_value.py':'def test_value():assert 1==1\n'},['tests/test_value.py'])
    with pytest.raises(ValueError):
        enrich_sources(c,f,tmp_path,**kwargs)
