import copy
import json
import shutil
import subprocess
import pytest
from pathlib import Path
from anchor_retrieval.syntax import Source
from generic_composition.corpus import build_corpus
from generic_composition.emitter import emit
from prototypes.test_action_and_oracle_transfer.proposals import generate,materialize,_expected
from prototypes.test_action_and_oracle_transfer import oracle
from prototypes.observation_projection import generate_projections


def corpus_for(tmp_path,code,language='python'):
    filename={'python':'test_toy.py','go':'toy_test.go','typescript':'toy.test.ts'}[language]
    (tmp_path/filename).write_text(code)
    return build_corpus(tmp_path,language)


def completion(candidate,expression):
    result=oracle.validate_completions({'completions':[{'candidate_id':candidate['id'],'observe':0,'expected':expression,'guard':None}]},[candidate])
    assert result['accepted'] and not result['rejected'],result
    return result['accepted'][0]


def emitted(corpus,candidate,expression):
    result=emit(corpus,[materialize(corpus,candidate,completion(candidate,expression))])
    assert not result['unsupported'],result
    return result


PYTHON='''class Pair:
    def __init__(self, count, text, size, label):
        self.count, self.text, self.size, self.label = count, text, size, label
    def __eq__(self, other): return self.__dict__ == other.__dict__
def make(n): return Pair(n, '猫', -2, 'fixed')
def wrap(p): return Pair(p.count + 1, p.text + '!', p.size, p.label)
def test_plain():
    label = 'fixed'
    assert make(1) == Pair(count=1, text='猫', size=-2, label=label)
def test_wrapped():
    label = 'fixed'
    assert wrap(make(2)) == Pair(count=3, text='猫!', size=-2, label=label)
'''


def test_python_constructor_vector_reconstruction_keeps_binding_and_field_names(tmp_path):
    corpus=corpus_for(tmp_path,PYTHON)
    generated=generate(corpus)
    candidate=next(c for c in generated['candidates'] if c.get('expected_template') and 'wrap(make(1))' in c['preview_body'])
    assert oracle.decode_value(candidate['pre'][0]) == (1,'猫',-2)
    assert 'label=label' in candidate['preview_body']
    assert not candidate.get('witnesses')
    result=emitted(corpus,candidate,"(pre[0][0] + 1, pre[0][1] + '!', pre[0][2])")
    code=result['files']['test_toy.py']
    assert "Pair(count=2, text='猫!', size=-2, label=label)" in code
    namespace={};exec(code,namespace)
    for row in result['controls']+result['obligations']:namespace[row['test_name']]()


def test_template_arity_type_and_model_shape_fields_are_rejected(tmp_path):
    corpus=corpus_for(tmp_path,PYTHON)
    candidate=next(c for c in generate(corpus)['candidates'] if c.get('expected_template'))
    for expression in ["(1, 'x')", "(True, 'x', -2)", "{'shape': 'raise RuntimeError()'}"]:
        result=oracle.validate_completions({'completions':[{'candidate_id':candidate['id'],'observe':0,'expected':expression,'guard':None}]},[candidate])
        assert not result['accepted']
    result=oracle.validate_completions({'completions':[{'candidate_id':candidate['id'],'observe':0,'expected':'pre[0]','guard':None,'template':'injected'}]},[candidate])
    assert result['protocol_error']['code']=='completion_schema'
    accepted=completion(candidate,'pre[0]')
    with pytest.raises(ValueError,match='completion_literal_mismatch'):
        materialize(corpus,candidate,dict(accepted,literal="Pair(0, '', 0, '')\n    raise RuntimeError()"))


def test_unique_literal_does_not_take_selector_index_as_expected_value(tmp_path):
    code='''def test_selector():
    other = source()
    assert actual() == other[0]
'''
    corpus=corpus_for(tmp_path,code)
    with pytest.raises(ValueError):
        _expected(corpus,corpus['capsules'][0],Source('test_toy.py',code,'python'),{})


def test_static_expected_old_path_unchanged(tmp_path):
    code='''def test_static():
    assert actual() == {'a': [1, 2], 'b': 3}
'''
    corpus=corpus_for(tmp_path,code)
    _,value,provenance=_expected(corpus,corpus['capsules'][0],Source('test_toy.py',code,'python'),{})
    assert value=={'a':[1,2],'b':3}
    assert provenance=={'kind':'literal'}


def test_single_value_hole_keeps_scalar_pre_and_literal_replacement(tmp_path):
    code='''def test_single():
    assert actual() == Box(
        value=-2, key=other[0], data={"fixed": bound})
'''
    corpus=corpus_for(tmp_path,code)
    span,value,provenance=_expected(corpus,corpus['capsules'][0],Source('test_toy.py',code,'python'),{})
    assert value == -2
    assert code.encode()[span['start_byte']:span['end_byte']] == b'-2'
    assert span['line'] == span['end_line'] == 3
    assert provenance['kind'] == 'single_literal_in_source_expected'


def test_model_presentation_declares_vector_values_and_fixed_expression(tmp_path):
    from prototypes.test_action_and_oracle_transfer import model
    corpus=corpus_for(tmp_path,PYTHON)
    generated=generate(corpus)
    candidate=next(c for c in generated['candidates'] if c.get('expected_template') and 'wrap(make(1))' in c['preview_body'])
    pending={'candidates':[candidate], 'shown_ids':[candidate['candidate_id']]}
    shown=model.presentation(corpus,{},pending)
    hole=shown['candidates'][0]['expected_hole']
    assert hole['mode'] == 'source_expected_template'
    assert hole['original_text'] == candidate['expected_template']['text']
    assert hole['source_expected_slot'] == 0
    assert [h['vector_index'] for h in hole['value_holes']] == [0,1,2]
    assert [h['value_type'] for h in hole['value_holes']] == ['int','str','int']
    assert [h['original_text'] for h in hole['value_holes']] == ['1',"'猫'",'-2']
    payload={'completions':[{'candidate_id':'c0','observe':0,'expected':"(pre[0][0]+1, pre[0][1]+'!', pre[0][2])",'guard':None}]}
    resolved=model.resolve_completion(json.dumps(payload),pending)
    assert resolved['accepted'][0]['candidate_id'] == candidate['candidate_id']
    assert resolved['accepted'][0]['oracle_mode'] == 'source_expected_template'
    assert not resolved['rejected']


GO_STRUCT='''package toy
import "testing"
type Pair struct { A int; B string }
func makePair(n int) Pair { return Pair{A:n, B:"猫"} }
func wrap(p Pair) Pair { return Pair{A:p.A+1, B:p.B+"!"} }
func TestPlain(t *testing.T) {
 if makePair(1) != (Pair{A:1, B:"猫"}) { t.Fatal("mismatch") }
}
func TestWrapped(t *testing.T) {
 if wrap(makePair(2)) != (Pair{A:3, B:"猫!"}) { t.Fatal("mismatch") }
}
'''


GO_MAP='''package toy
import "testing"
import "reflect"
type Numbers map[string]int
var assert = struct{ Equal func(*testing.T, any, any) }{
 Equal: func(t *testing.T, expected any, actual any) {
  if !reflect.DeepEqual(expected, actual) { t.Fatal("mismatch") }
 },
}
func makeMap(n int) Numbers { return Numbers{"x":n, "y":n+1} }
func wrap(p Numbers) Numbers { return Numbers{"x":p["x"]+10, "y":p["y"]+10} }
func TestPlain(t *testing.T) { assert.Equal(t, Numbers{"x":1, "y":2}, makeMap(1)) }
func TestWrapped(t *testing.T) { assert.Equal(t, Numbers{"x":12, "y":13}, wrap(makeMap(2))) }
'''


@pytest.mark.skipif(shutil.which('go') is None, reason='Go unavailable')
@pytest.mark.parametrize('code,target,expression,wrapper',[
 (GO_STRUCT,'wrap(makePair(1))',"(pre[0][0]+1, pre[0][1]+'!')",'Pair{A:2, B:"猫!"}'),
 (GO_MAP,'wrap(makeMap(1))','(pre[0][0]+10, pre[0][1]+10)','Numbers{"x":11, "y":12}'),
])
def test_go_typed_struct_and_alias_map_keep_source_wrappers(tmp_path,code,target,expression,wrapper):
    corpus=corpus_for(tmp_path,code,'go')
    generated=generate(corpus)
    candidate=next(c for c in generated['candidates'] if c.get('expected_template') and target in c['preview_body'])
    result=emitted(corpus,candidate,expression)
    output=tmp_path/'toy_test.go';output.write_text(result['files']['toy_test.go'])
    assert wrapper in output.read_text()
    run=subprocess.run(['go','test',str(output)],capture_output=True,text=True,timeout=45)
    assert run.returncode==0,run.stdout+run.stderr


TS_OBJECT='''import assert from 'node:assert/strict';
import {test} from 'node:test';
function make(n) { return {count:n, text:'猫', tag:'fixed'}; }
function wrap(p) { return {count:p.count+1, text:p.text+'!', tag:p.tag}; }
test('plain', () => {
 const binding = 'fixed';
 assert.deepEqual(make(1), {count:1, text:'猫', tag:binding});
});
test('wrapped', () => {
 const binding = 'fixed';
 assert.deepEqual(wrap(make(2)), {count:3, text:'猫!', tag:binding});
});
'''


@pytest.mark.skipif(shutil.which('node') is None, reason='Node unavailable')
def test_typescript_source_object_preserves_keys_and_unknown_binding(tmp_path):
    corpus=corpus_for(tmp_path,TS_OBJECT,'typescript')
    generated=generate(corpus)
    candidate=next(c for c in generated['candidates'] if c.get('expected_template') and 'wrap(make(1))' in c['preview_body'])
    assert oracle.decode_value(candidate['pre'][0])==(1,'猫')
    result=emitted(corpus,candidate,"(pre[0][0]+1, pre[0][1]+'!')")
    code=result['files']['toy.test.ts']
    assert 'count:2' in code and 'tag:binding' in code
    output=tmp_path/'toy.mjs';output.write_text(code)
    run=subprocess.run(['node',str(output)],capture_output=True,text=True,timeout=20)
    assert run.returncode==0,run.stdout+run.stderr


def test_changed_observation_does_not_inherit_expected_template(tmp_path):
    code=PYTHON + '''def test_scalar_observer():
    p = Pair(1, '猫', -2, 'fixed')
    assert p.count == 1
'''
    corpus=corpus_for(tmp_path,code)
    pending=[c for c in generate(corpus)['candidates'] if c.get('expected_template') and not c.get('projection')]
    assert pending
    projected=generate_projections(corpus,pending)
    assert projected['candidates']
    assert all('expected_template' not in c for c in projected['candidates'])
    assert all(c.get('expected_template') for c in pending)
