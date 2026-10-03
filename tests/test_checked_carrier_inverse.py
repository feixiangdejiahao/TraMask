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


def test_scalar_probe_fetches_container_without_invoking_factory_or_claiming_a_defect():
    source, corpus, frontend = fixture()
    for pair in relation.generate(corpus, frontend, ISSUE)['pairs']:
        probe = pair['probe']
        assert probe['oracle_status'] == 'precondition_only_never_a_defect_alert'
        tail = probe['edits'][1]['after']
        assert '.Lookup(' in tail and '.Object()).(*guest.Vector).Elements[' in tail
        assert 'Invoke' not in tail and 'check(' not in tail
        assert ':=[' in probe['edits'][0]['after']
        assert not emit(corpus, [probe])['unsupported']


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
