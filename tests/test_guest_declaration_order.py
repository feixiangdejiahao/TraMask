import copy

import pytest

from anchor_retrieval.syntax import Source
from generic_composition.emitter import emit
from relational_gap.frontend import extract_frontend, to_emitter_corpus
from relation_search import guest_declaration_order as relation

CODE = '''package sample_test
import ("example.org/runtime"; "testing"; "example.org/assert")
func prepare(t *testing.T, code string) *runtime.Compiled {
 script := runtime.New([]byte(code))
 compiled, err := script.Start()
 assert.NoError(t, err)
 return compiled
}
func fetch(t *testing.T, compiled *runtime.Compiled, name string) *runtime.Function {
 object := compiled.Lookup(name).Object()
 fn, ok := object.(*runtime.Function)
 assert.True(t, ok)
 return fn
}
func TestFactory(t *testing.T) {
 c := prepare(t, `make := func(x) { return func(y) {return x+y} }`)
 fn := fetch(t, c, "make")
 result, err := fn.Invoke(integer(7))
 assert.NoError(t,err)
 _=result
}
func TestTransfer(t *testing.T) {
 a := prepare(t, `g := 100
make := func() {n:=0; return func(){n++;return n+g}}
counter := make()
`)
 b := prepare(t, `g := 5000
counter := undefined
`)
 assert.NoError(t, b.Store("counter", a.Lookup("counter").Object()))
 fn := fetch(t, b, "counter")
 result, err := fn.Invoke()
 assert.NoError(t,err)
 assert.Equal(t,int64(5001),result.(*runtime.Int).Value)
}
'''


def fixture(code=CODE):
    source = Source('sample_test.go', code, 'go', 'repository')
    frontend = extract_frontend([source])
    return source, to_emitter_corpus(frontend), frontend


def test_source_named_state_commutation_keeps_complete_host_test_and_expected_value():
    source, corpus, frontend = fixture()
    original = copy.deepcopy((corpus, frontend))
    generated = relation.generate(corpus, frontend)
    assert generated['total_candidates'] == 1
    candidate = generated['candidates'][0]
    assert candidate['source_test_ids'] == [candidate['base_test_id']]
    assert len(candidate['edits']) == 1
    assert candidate['edits'][0]['after'] == '`counter := undefined\ng := 5000\n`'
    material = emit(corpus, [candidate])
    assert not material['unsupported']
    code = material['files'][source.path]
    assert 'assert.Equal(t,int64(5001),result.(*runtime.Int).Value)' in code
    assert 'b.Store("counter", a.Lookup("counter").Object())' in code
    assert 'result, err := fn.Invoke()' in code
    assert not Source(source.path, code, 'go').root.has_error
    assert (corpus, frontend) == original


@pytest.mark.parametrize('program', [
    'first := 1\nsecond := first\n',
    'first := effect()\nsecond := 2\n',
    'first := [1]\nsecond := 2\n',
    'first := 1\n// comment separates declarations\nsecond := 2\n',
    'first := 1\nsecond := 2\nfirst := 3\n',
    'first := 1\nsecond := 2\nf := func(first) {return first}\n',
    'first := 1\nsecond := 2\nf := func() {first := 5}\n',
    'f := func() {\nfirst := 1\nsecond := 2\n}\n',
    '//line file:5\nfirst := 1\nsecond := 2\n',
    'first := 1\nsecond := 2\nfor first in xs {}\n',
])
def test_dependencies_calls_shadowing_nonadjacency_and_nested_scope_abstain(program):
    assert not relation.declaration_pairs(program)


@pytest.mark.parametrize('scalar', ['-3', '+0.25', 'true', 'false', 'undefined', '"x := effect()"', "'x'", '1e3', '0x10'])
def test_closed_scalars_are_values_not_token_text_inside_strings(scalar):
    assert len(relation.declaration_pairs('first := '+scalar+'\nsecond := 2\n')) == 1


def test_final_line_without_newline_does_not_concatenate_declarations():
    source, corpus, frontend = fixture(CODE.replace('counter := undefined\n`', 'counter := undefined`'))
    candidate = relation.generate(corpus, frontend)['candidates'][0]
    assert candidate['edits'][0]['after'] == '`counter := undefined\ng := 5000`'
    assert not Source(source.path, emit(corpus, [candidate])['files'][source.path], 'go').root.has_error


def test_compile_chain_and_success_only_runtime_step_are_not_text_observations():
    code = CODE.replace('b := prepare(t, `g := 5000', 'script := prepare(t, `g := 5000').replace(
        'counter := undefined\n`)\n assert.NoError(t, b.Store',
        'counter := undefined\n`)\n b, err := script.Start()\n assert.NoError(t,err)\n assert.NoError(t,b.Ready())\n assert.NoError(t, b.Store')
    _, corpus, frontend = fixture(code)
    assert relation.generate(corpus, frontend)['total_candidates'] == 1


@pytest.mark.parametrize(('before', 'after'), [
    ('script := runtime.New([]byte(code))', 'assert.Equal(t,"source",code)\n script := runtime.New([]byte(code))'),
    ('script := runtime.New([]byte(code))', 'copy := code\n script := runtime.New([]byte(copy))'),
    ('assert.NoError(t,err)\n assert.Equal', 'assert.EqualError(t,err,"line 3")\n assert.Equal'),
    ('assert.Equal(t,int64(5001),result.(*runtime.Int).Value)', 'assert.Equal(t,"g := 5000",b.Source())'),
    ('assert.Equal(t,int64(5001),result.(*runtime.Int).Value)', 'assert.Equal(t,expected,b)'),
    ('fn := fetch(t, b, "counter")', 'assert.Equal(t,42,b.Position())\n fn := fetch(t, b, "counter")'),
    ('object := compiled.Lookup(name).Object()', 'assert.Equal(t,"original",compiled.Source())\n object := compiled.Lookup(name).Object()'),
    ('return fn\n}', 'assert.Equal(t,2,fn.SourceMap[0])\n return fn\n}'),
    ('func TestFactory(t *testing.T)', 'func unrelatedFactory(t *testing.T)'),
])
def test_raw_text_diagnostics_direct_object_observations_and_missing_language_anchor_abstain(before, after):
    _, corpus, frontend = fixture(CODE.replace(before, after))
    assert not relation.generate(corpus, frontend)['candidates']


def test_labels_do_not_select_candidates_and_changed_source_bytes_are_refused():
    _, corpus, frontend = fixture()
    expected = relation.generate(corpus, frontend)
    corpus['evaluation'] = {'would_fail': True, 'case': 'any'}
    assert relation.generate(corpus, frontend) == expected
    corpus = copy.deepcopy(corpus)
    corpus['sources']['sample_test.go']['code'] += '\n'
    with pytest.raises(ValueError, match='frontend_source_mismatch'):
        relation.generate(corpus, frontend)


def test_language_gate_has_no_programs_for_non_go_sources():
    assert relation.generate({'language':'python'}, {})['status'] == 'language_unsupported'


def test_native_confirmation_requires_controls_and_exact_transport():
    from scripts import run_guest_declaration_order_search as runner
    valid = dict(transport={'status':'matched'}, native={
        'controlled_failure':True, 'controls':{'status':'all_source_controls_passed'}})
    assert runner._controlled(valid)
    for field, value in [('transport', {'status':'mismatch'}),
                         ('native', {'controlled_failure':True,'controls':{'status':'missing'}}),
                         ('native', {'controlled_failure':False,'controls':{'status':'all_source_controls_passed'}})]:
        changed=copy.deepcopy(valid);changed[field]=value
        assert not runner._controlled(changed)
