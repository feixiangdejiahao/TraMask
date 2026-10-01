"""Applicability checks on independent contracts, including negative tests."""
import copy
import json

import pytest

from anchor_retrieval.syntax import Source
from relational_gap.frontend import extract_frontend, to_emitter_corpus
from relation_search.test_preconditions import analyze


def setup(language, code, before, after, extra=None, imports=None):
    path = {'python':'tests/test_applicability.py', 'go':'applicability_test.go',
            'typescript':'tests/applicability.test.ts'}[language]
    sources = [Source(path, code, language)] + [Source(p,c,language) for p,c in (extra or {}).items()]
    frontend = extract_frontend(sources)
    corpus = to_emitter_corpus(frontend)
    test_id = next(t['id'] for t in frontend['tests'])
    span = corpus['tests'][test_id]['span']
    start = code.encode().index(before.encode(), span['start_byte'])
    candidate = dict(id='without_label', base_test_id=test_id, source_test_ids=[], imports=imports or [],
                     edits=[dict(span=dict(path=path,start_byte=start,end_byte=start+len(before.encode())),
                                 before=before, after=after, role='input')])
    return corpus,frontend,candidate


@pytest.mark.parametrize('language,code,before,after', [
    ('python','def combine(a,b): return a+b\ndef test_case():\n    assert combine(1,2) == 3\n','combine(1,2)','combine(1)'),
    ('go','package demo\nimport "testing"\nfunc combine(a,b int) int {return a+b}\nfunc TestCase(t *testing.T) { if combine(1,2)!=3 {t.Fatal("bad")} }','combine(1,2)','combine(1)'),
    ('typescript',"function combine(a:number,b:number){return a+b;}\ntest('x',()=>{expect(combine(1,2)).toBe(3);});",'combine(1,2)','combine(1)'),
])
def test_exact_missing_required_argument_is_rejected(language,code,before,after):
    result=analyze(*setup(language,code,before,after))
    assert result['status']=='invalid'
    assert any(f['code']=='call_signature_contradiction' for f in result['findings'])


@pytest.mark.parametrize('signature,after', [('a,b=2','combine(1)'), ('a,*items','combine(1,2,3)'),
                                          ('a,*,b','combine(1,b=2)'), ('a,**items','combine(1,x=2)')])
def test_python_defaults_and_argument_kinds_are_not_guessed(signature,after):
    result=analyze(*setup('python',f'def combine({signature}): return a\ndef test_case():\n    assert combine(1,2) == 1\n',
                         'combine(1,2)',after))
    assert result['status']!='invalid'


def test_python_default_expressions_are_never_evaluated():
    result=analyze(*setup('python','def combine(a,b=explode()): return a\ndef test_case():\n    assert combine(1,2)==1\n',
                         'combine(1,2)','combine(1)'))
    assert result['status']!='invalid'


@pytest.mark.parametrize('after', ['combine(*items)', 'combine(**options)'])
def test_spread_inputs_remain_unknown(after):
    result=analyze(*setup('python','def combine(a,b): return a+b\ndef test_case():\n    assert combine(1,2)==3\n',
                         'combine(1,2)',after))
    assert result['status']=='review'
    assert any(f['code']=='call_signature_not_proved' for f in result['findings'])


def test_existing_exception_observation_preserves_negative_api_test():
    result=analyze(*setup('python','import pytest\ndef combine(a,b): return a+b\ndef test_case():\n    with pytest.raises(TypeError):\n        combine(1,2)\n',
                         'combine(1,2)','combine(1)'))
    contradiction=next(f for f in result['findings'] if f['code']=='call_signature_contradiction')
    assert contradiction['severity']=='review'
    assert result['status']!='invalid'


def test_try_handler_does_not_turn_negative_call_into_proved_invalid_test():
    result=analyze(*setup('python','def combine(a,b): return a+b\ndef test_case():\n    try:\n        combine(1,2)\n    except TypeError:\n        pass\n',
                         'combine(1,2)','combine(1)'))
    assert result['status']!='invalid'


def test_type_discriminant_is_independent_of_api_and_property_names():
    result=analyze(*setup('typescript', '''interface Accepts {readonly phase:'immediate'}
function assemble<T extends Accepts>(value:T,step:unknown):unknown{return value}
function producer(){return {phase:'deferred'}}
function original(){return {phase:'immediate'}}
test('case',()=>{expect(assemble(original(), 1)).toBe(1)});
''','original()','producer()'))
    findings=[f for f in result['findings'] if f['code']=='declared_literal_property_contradiction']
    assert result['status']=='invalid'
    assert findings[0]['evidence'][0]['property']=='phase'
    assert findings[0]['evidence'][0]['required']=='immediate'
    assert findings[0]['evidence'][0]['returned']=='deferred'


def test_overloaded_formal_contract_follows_import_and_inheritance():
    extra={
        'lib/types.ts':'export interface Base {readonly completed:false} export interface Derived extends Base {}',
        'lib/index.ts':"export * from './types'; export * from './ops';",
        'lib/ops.ts':"""import type {Derived} from './types';
export function assemble<T extends Derived>(schema:T,step:number):unknown;
export function assemble<T extends Derived>(schema:T,a:number,b:number):unknown;
export function assemble(...parts:unknown[]):unknown{return parts[0]}
export function producer(){return {completed:true}}
""",
    }
    result=analyze(*setup('typescript', "import {producer} from '../lib';\nfunction original(){return {completed:false}}\ntest('case',()=>{expect(unknown(original(),1)).toBe(1)});",
        'unknown(original(),1)','generated(producer(),1)',extra,
        [dict(name='generated',module='../lib',imported_name='assemble',source_path='tests/applicability.test.ts')]))
    assert result['status']=='invalid'
    assert any(f['code']=='declared_literal_property_contradiction' for f in result['findings'])


@pytest.mark.parametrize('producer', ['function producer(){return {completed:false}}',
                                    'function producer(flag:boolean){return flag?{completed:true}:{completed:false}}',
                                    'function producer(){return opaque()}',
                                    'function producer(){return {completed:true,...options}}'])
def test_no_invalid_when_literal_return_is_compatible_or_unknown(producer):
    code=f'''interface Accepts {{readonly completed:false}}
function assemble(value:Accepts){{return value}}
{producer}
function original(){{return {{completed:false}}}}
test('case',()=>{{expect(assemble(original())).toBe(1)}});
'''
    # A required producer parameter gets a source-compatible argument here.
    replacement='producer(true)' if 'flag:boolean' in producer else 'producer()'
    result=analyze(*setup('typescript',code,'original()',replacement))
    assert result['status']!='invalid'


def test_overload_with_compatible_discriminant_prevents_false_rejection():
    code='''interface A {ready:false} interface B {ready:true}
function assemble(value:A):unknown;
function assemble(value:B):unknown;
function assemble(value:unknown):unknown{return value}
function producer(){return {ready:true}}
function original(){return {ready:false}}
test('case',()=>{expect(assemble(original())).toBe(1)});
'''
    result=analyze(*setup('typescript',code,'original()','producer()'))
    assert result['status']!='invalid'


def test_optional_property_is_not_a_required_discriminant():
    code='''interface A {ready?:false}
function assemble(value:A){return value}
function producer(){return {ready:true}}
function original(){return {ready:false}}
test('case',()=>{expect(assemble(original())).toBe(1)});
'''
    assert analyze(*setup('typescript',code,'original()','producer()'))['status']!='invalid'


def test_unknown_call_is_not_invalid_and_input_is_not_mutated():
    c,f,k=setup('python','def test_case():\n    assert external(1)==1\n','external(1)','external(2)')
    frozen=json.dumps([c,f,k],sort_keys=True)
    result=analyze(c,f,k)
    assert result['status']=='review'
    assert analyze(c,f,k)==result
    assert frozen==json.dumps([c,f,k],sort_keys=True)


def test_probe_only_edit_does_not_affect_source_applicability():
    c,f,k=setup('python','def combine(a,b):return a+b\ndef test_case():\n    assert combine(1,2)==3\n',
                'combine(1,2)','combine(1)')
    original=analyze(c,f,k)
    k['program_edits']=copy.deepcopy(k['edits'])
    k['instrumentation']=dict(status='instrumented')
    k['edits'][0]['after']='unbound_probe(combine(1))'
    assert analyze(c,f,k)==original
