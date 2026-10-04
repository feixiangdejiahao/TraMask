import copy

import pytest

from anchor_retrieval.syntax import Source
from experimental import relation_search_go_ts as neighbors
from generic_composition.emitter import emit
from relational_gap.frontend import extract_frontend, to_emitter_corpus
from relation_search import checked_carrier_inverse as relation

ISSUE = 'Returned closures and composite values must stay callable.'
CODE = '''package sample_test
import ("example.org/guest"; "testing")
func TestCalls(t *testing.T) {
 c := run(`build := func(seed) { n:=seed; return func(x){n+=x;return n} }`)
 result, err := c.Lookup("build").Object().Invoke(integer(3))
 assertNoError(t, err)
 check(t, 4, invoke(result,integer(1)))
 check(t, 5, invoke(result,integer(1)))
}
func TestCarrier(t *testing.T) {
 c:=run(`[0]`)
 holder := c.Lookup("list").Object().(*guest.Vector)
 _=holder.Elements[0]
}
'''

HELPER_CODE = CODE.replace('c := run(`', 'c := prepare(t, `', 1).replace(
    'return n} }`)\n result, err := c.Lookup("build").Object().Invoke(integer(3))',
    'return n} }`, nil)\n selected := fetch(t, c, "build")\n result, err := selected.Invoke(integer(3))'
) + '''
func prepare(t *testing.T, src string, variables map[string]interface{}) *guest.Compiled {
 vm := guest.Load([]byte(src))
 for k, v := range variables { assertNoError(t, vm.Bind(k,v)) }
 compiled, err := vm.Start()
 assertNoError(t, err)
 return compiled
}
func fetch(t *testing.T, compiled *guest.Compiled, symbol string) *guest.Function {
 object := compiled.Lookup(symbol).Object()
 function, ok := object.(*guest.Function)
 assertTrue(t, ok, object)
 return function
}
'''


def fixture(code=CODE):
    source = Source('sample_test.go', code, 'go', 'repository')
    frontend = extract_frontend([source])
    return source, to_emitter_corpus(frontend), frontend


def candidate_row(source):
    return neighbors._guest_container_neighbors(source, [])[0]


def test_inverse_preserves_closure_body_all_observers_and_two_source_controls():
    source, corpus, frontend = fixture()
    before = copy.deepcopy((corpus, frontend))
    generated = relation.generate(corpus, frontend, ISSUE)
    assert generated['total_candidates'] == 2
    for pair in generated['pairs']:
        candidate = pair['candidate']
        assert len(candidate['source_test_ids']) == 2
        assert sum(e['role'] == 'projection' for e in candidate['edits']) == 2
        material = emit(corpus, [candidate])
        assert not material['unsupported']
        code = material['files'][source.path]
        assert 'return [func(x){n+=x;return n}]' in code or 'return [0, func(x){n+=x;return n}]' in code
        assert 'check(t, 4, invoke((result)' in code
        assert 'check(t, 5, invoke((result)' in code
        assert not Source(source.path, code, 'go').root.has_error
    assert (corpus, frontend) == before


def test_scalar_probe_preserves_factory_path_without_claiming_a_defect():
    source, corpus, frontend = fixture()
    for pair in relation.generate(corpus, frontend, ISSUE)['pairs']:
        probe = pair['probe']
        assert probe['oracle_status'] == 'precondition_only_never_a_defect_alert'
        tail = probe['edits'][-1]['after']
        assert '(result).(*guest.Vector).Elements[' in tail
        assert '_ = err' in tail and 'check(' not in tail
        assert 'return [0]' in probe['edits'][0]['after'] or 'return [0, 0]' in probe['edits'][0]['after']
        material = emit(corpus, [probe])
        assert not material['unsupported']
        code = material['files'][source.path]
        assert '.Object().Invoke(integer(3))' in code
        assert not Source(source.path, code, 'go').root.has_error


@pytest.mark.parametrize('replacement', [
    'build := func(seed) { if seed<0{return undefined}; n:=seed; return func(x){n+=x;return n} }',
    'build := func(seed) { n:=seed; return func(x){return build(x)} }',
    'outer := func() { build := func(seed) { n:=seed; return func(x){n+=x;return n} }; return build }',
])
def test_other_factory_return_paths_self_reference_and_nested_scope_are_refused(replacement):
    code = CODE.replace('build := func(seed) { n:=seed; return func(x){n+=x;return n} }', replacement)
    _, corpus, frontend = fixture(code)
    assert not relation.generate(corpus, frontend, ISSUE)['pairs']


def test_lookup_must_belong_to_the_same_program_owner():
    code = CODE.replace(' result, err := c.Lookup', ' other := run(`other:=0`)\n result, err := other.Lookup')
    _, corpus, frontend = fixture(code)
    generated = relation.generate(corpus, frontend, ISSUE)
    assert not generated['pairs']
    assert any(row['reason'] == 'lookup_owner_does_not_trace_to_guest_program' for row in generated['skipped'])


def test_program_owner_can_have_one_compile_or_run_boundary():
    code = CODE.replace(' c := run(`', ' script := buildVM(`').replace(' result, err :=', ' c, err := script.Start()\n assertNoError(t,err)\n result, err :=')
    _, corpus, frontend = fixture(code)
    assert len(relation.generate(corpus, frontend, ISSUE)['pairs']) == 2


@pytest.mark.parametrize('extra', ['\n result = other', '\n observe(func(){invoke(result,integer(1))})'])
def test_reassigned_or_captured_results_are_refused(extra):
    code = CODE.replace('\n check(t, 5, invoke(result,integer(1)))', extra+'\n check(t, 5, invoke(result,integer(1)))')
    _, corpus, frontend = fixture(code)
    assert not relation.generate(corpus, frontend, ISSUE)['pairs']


@pytest.mark.parametrize('part', ['factory', 'projection', 'missing_use', 'view'])
def test_checker_rejects_tampered_constructor_metadata_or_noninverse_edits(part):
    source, _, _ = fixture()
    row = copy.deepcopy(candidate_row(source))
    if part == 'factory':
        row['edits'][0]['after'] = row['edits'][0]['after'].replace('n+=x', 'n+=2*x')
    elif part == 'projection':
        row['edits'][2]['after'] += '.Wrong'
    elif part == 'missing_use':
        row['edits'].pop()
    else:
        row['evidence']['host_view']['base_suffix'] = '.(*guest.Other).Elements'
    with pytest.raises(ValueError):
        relation.check(source, {source.path: source}, neighbors._tests(source)[0], row)


@pytest.mark.parametrize('issue', ['', 'Returned closures may remain callable.',
    'Returned closures and composite values must not remain callable.',
    'Returned closures and composite values must stay callable only when owned.',
    'It is false that returned closures and composite values must stay callable.'])
def test_contract_with_missing_composite_obligation_or_qualifiers_is_not_a_premise(issue):
    _, corpus, frontend = fixture()
    assert not relation.generate(corpus, frontend, issue)['pairs']


def test_generation_ignores_evaluation_labels_and_refuses_changed_source_bytes():
    _, corpus, frontend = fixture()
    before = relation.generate(corpus, frontend, ISSUE)
    corpus['evaluation'] = {'valid': False}
    assert relation.generate(corpus, frontend, ISSUE) == before
    corpus = copy.deepcopy(corpus)
    corpus['sources']['sample_test.go']['code'] += '\n'
    with pytest.raises(ValueError, match='frontend_source_mismatch'):
        relation.generate(corpus, frontend, ISSUE)


def test_helpers_keep_setup_checks_invocation_and_all_original_observers():
    source, corpus, frontend = fixture(HELPER_CODE)
    generated = relation.generate(corpus, frontend, ISSUE)
    assert generated['total_candidates'] == 2
    for pair in generated['pairs']:
        full = emit(corpus, [pair['candidate']])
        probe = emit(corpus, [pair['probe']])
        assert not full['unsupported'] and not probe['unsupported']
        candidate_code, probe_code = full['files'][source.path], probe['files'][source.path]
        for code in (candidate_code, probe_code):
            assert 'selected := fetch(t, c,' in code
            assert 'result, err := selected.Invoke(integer(3))' in code
            assert HELPER_CODE[HELPER_CODE.index('func prepare'):].strip() in code
            assert not Source(source.path, code, 'go').root.has_error
        assert 'check(t, 4, invoke((result)' in candidate_code
        assert 'check(t, 5, invoke((result)' in candidate_code
        assert '_ = (result).(*guest.Vector).Elements[' in probe_code


def test_nested_helper_return_and_parameter_binding_are_compositional():
    code = HELPER_CODE.replace('c := prepare(t,', 'c := prepareOuter(t,') + '''
func prepareOuter(t *testing.T, src string, variables map[string]interface{}) *guest.Compiled {
 return prepare(t, src, variables)
}
'''
    _, corpus, frontend = fixture(code)
    assert relation.generate(corpus, frontend, ISSUE)['total_candidates'] == 2


def test_lookup_can_be_stored_in_one_local_before_invocation():
    code = CODE.replace('result, err := c.Lookup("build").Object().Invoke(integer(3))',
                        'selected := c.Lookup("build").Object()\n result, err := selected.Invoke(integer(3))')
    _, corpus, frontend = fixture(code)
    assert relation.generate(corpus, frontend, ISSUE)['total_candidates'] == 2


@pytest.mark.parametrize(('before', 'after'), [
    ('[]byte(src)', '[]byte("unrelated:=1")'),
    ('return compiled', 'return prepare(t,src,variables)'),
    ('return compiled', 'if condition { return other }; return compiled'),
    ('return compiled', 'compiled = other; return compiled'),
    ('vm := guest.Load', 'src = "unrelated:=1"; vm := guest.Load'),
    ('return compiled', 'defer release(compiled); return compiled'),
    ('return compiled', 'go release(compiled); return compiled'),
    ('return compiled', 'return err'),
    ('Lookup(symbol)', 'Lookup("unrelated")'),
    ('return function', 'function = other; return function'),
    ('object := compiled.Lookup', 'symbol = "unrelated"; object := compiled.Lookup'),
    ('result, err := selected.Invoke', 'selected = other; result, err := selected.Invoke'),
    ('selected := fetch(t, c,', 'fetch := other; selected := fetch(t, c,'),
    ('selected := fetch(t, c,', 'fetch, ok := other.(func(*testing.T,*guest.Compiled,string) *guest.Function); _=ok; selected := fetch(t, c,'),
    ('selected := fetch(t, c,', 'var ignored, fetch = other, other; _=ignored; selected := fetch(t, c,'),
    ('variables map[string]interface{}) *guest.Compiled {', 'variables map[string]interface{}) (compiled *guest.Compiled) {'),
])
def test_unproved_helper_origins_and_rebindings_are_refused(before, after):
    _, corpus, frontend = fixture(HELPER_CODE.replace(before, after))
    generated = relation.generate(corpus, frontend, ISSUE)
    assert not generated['pairs']
    assert generated['skipped']


def test_source_helper_definition_is_required_instead_of_trusting_call_arguments():
    code = CODE + '''
func run(src string) *guest.Compiled {
 return unrelatedProgram()
}
'''
    _, corpus, frontend = fixture(code)
    assert not relation.generate(corpus, frontend, ISSUE)['pairs']
