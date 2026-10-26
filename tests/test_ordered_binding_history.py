"""Generic source fixtures only: no subject runs, model calls or evaluation truth."""
import hashlib

import pytest

from anchor_retrieval.syntax import Source, walk
from prototypes.ordered_binding_history import analyze_source


def py(body):
    return analyze_source('def test_case(context):\n' + '\n'.join('    ' + line for line in body.splitlines()) + '\n',
                          'python', root_name='test_case')


def names(result):
    bindings = {b['id']:b['name'] for b in result['bindings']}
    return [bindings[g['binding']] for g in result['groups']]


def test_receiver_and_argument_reuse_keeps_interleaved_operations_and_observations():
    result = py('handle = make()\nhandle.step()\nother()\nassert inspect(handle) == 4\nhandle.step()\nassert inspect(handle) == 5')
    assert names(result) == ['handle']
    group = result['groups'][0]
    assert len(group['uses']) == 4
    assert [result['calls'][int(c[1:])]['callee'] for c in group['interval_call_ids']] == [
        'handle.step','other','inspect','handle.step','inspect']
    assert len(result['observations']) == 2
    assert result['observations'][0]['lexical_calls_before_or_inside_site'] == ['C0','C1','C2','C3']
    assert group['heap_identity'] == group['state_equality'] == 'not_inferred'
    assert group['opaque_argument_escape']


def test_renaming_does_not_change_group_structure_and_params_are_excluded():
    one = py('x = make()\ncontext.touch()\nx.step()\ncheck(x)\ncontext.touch()')
    two = py('renamed = make()\ncontext.touch()\nrenamed.step()\ncheck(renamed)\ncontext.touch()')
    assert [len(g['uses']) for g in one['groups']] == [len(g['uses']) for g in two['groups']] == [2]
    assert 'context' not in [b['name'] for b in one['bindings']]


def test_reassignment_splits_definition_versions_even_identical_factory_calls():
    result = py('x = get()\nuse(x)\nuse(x)\nx = get()\nuse(x)\nuse(x)')
    assert names(result) == ['x','x']
    assert result['groups'][0]['binding'] != result['groups'][1]['binding']
    assert result['bindings'][1]['previous_definition'] == 'B0'


def test_nested_call_order_is_child_before_parent_with_operand_roles():
    result = py('x = make()\nouter(x, inner(x))\nx()')
    assert [c['callee'] for c in result['calls']] == ['make','inner','outer','x']
    assert [u['roles'][0]['role'] for u in result['groups'][0]['uses']] == ['input','input','callee']


def test_alias_assignment_is_a_separate_binding_and_an_explicit_unknown():
    result = py('x = make()\ny = x\nuse(x)\nuse(y)\nuse(x)\nuse(y)')
    assert names(result) == ['x','y']
    assert result['bindings'][1]['direct_rhs_binding'] == 'B0'
    assert result['status'] == 'partial'
    assert any(u['reason']=='alias_or_value_copy_not_merged' for u in result['unknowns'])


@pytest.mark.parametrize('middle',[
    'if flag:\n    x = other()', 'for value in things:\n    use(x)',
    'with manager():\n    use(x)', 'def callback():\n    use(x)',
    'use(lambda: x)', 'x.field = other()', 'x = cond and other()',
])
def test_ambiguous_control_or_escape_is_barrier(middle):
    result = py('x = make()\nuse(x)\n'+middle+'\nuse(x)')
    assert not result['groups']
    assert result['unknowns']


def test_tuple_swap_uses_prior_versions_without_alias_merging():
    result = py('x = make()\ny = other()\nx,y = y,x\nuse(x)\nuse(x)\nuse(y)\nuse(y)')
    assert result['bindings'][2]['direct_rhs_binding'] == 'B1'
    assert result['bindings'][3]['direct_rhs_binding'] == 'B0'
    assert [g['binding'] for g in result['groups']] == ['B2','B3']


def test_assignment_rhs_reads_old_version_before_installing_new_one():
    result = py('x = make()\nuse(x)\nx = replace(x)\nuse(x)\nuse(x)')
    assert [g['binding'] for g in result['groups']] == ['B0','B1']
    assert result['groups'][0]['uses'][-1]['call'] == 'C2'


def test_opaque_get_and_container_reads_never_merge_with_direct_bindings():
    result = py('a = obj.get()\nb = obj.get()\nuse(a)\nuse(b)\nuse(box[0])\nuse(box[0])')
    assert not result['groups']


def test_source_refs_use_utf8_byte_positions():
    code='def test_case():\n    x = make("猫")\n    use(x)\n    use(x)\n'
    result=analyze_source(code,'python',path='sample.py',root_name='test_case')
    assert result['source_sha256']==hashlib.sha256(code.encode()).hexdigest()
    for call in result['calls']:
        ref=call['ref']; text=code.encode()[ref['start_byte']:ref['end_byte']].decode()
        assert text.startswith(call['callee'])


def test_go_multiresult_reassignment_and_parameter_exclusion():
    code='package p\nfunc TestCase(t *T) { x, err := make(); consume(t,x); x.Step(); err = other(); check(t,err); check(t,err); x = other(); x.Step() }'
    result=analyze_source(code,'go',path='sample_test.go',root_name='TestCase',parameter_names=['t'])
    assert names(result)==['x','err']
    assert len(result['bindings'])==4
    assert result['bindings'][0]['rhs_result_slot']==0
    assert result['bindings'][1]['rhs_result_slot']==1
    assert all(b['name']!='t' for b in result['bindings'])


def test_typescript_reassignment_and_callback_root():
    code='test("works", () => { let x=make(); x.step(); use(x); x=other(); x.step(); use(x); });'
    source=Source('sample.test.ts',code,'typescript')
    root=next(n for n in walk(source.root) if n.type=='arrow_function')
    result=analyze_source(code,'typescript',path=source.path,root_ref={'start_byte':root.start_byte,'end_byte':root.end_byte},parameter_names=[])
    assert names(result)==['x','x']
    assert result['bindings'][1]['previous_definition']=='B0'


def test_observation_in_helper_is_retained_without_a_made_up_phase():
    code='def test_case():\n    x=make()\n    use(x)\n    use(x)\n'
    obs=[dict(id='Q0',is_root=False,ref=dict(path='helper.py',start_byte=20,end_byte=40,version='modified'))]
    result=analyze_source(code,'python',root_name='test_case',observations=obs)
    assert result['observations'][0]['id']=='Q0'
    assert result['observations'][0]['phase_statement'] is None
    assert result['observations'][0]['phase_status']=='helper_or_unmapped_phase_unknown'


def test_added_local_address_escape_is_unknown_in_go():
    result=analyze_source('package p\nfunc TestCase() { x:=make(); use(x); change(&x); use(x) }','go',path='a.go',root_name='TestCase')
    assert not result['groups']
    assert result['unknowns']


def test_parameter_named_like_a_normal_object_is_still_excluded():
    result=analyze_source('def test_case(object):\n    object.step()\n    object.step()\n','python',root_name='test_case')
    assert not result['groups']


def test_parse_failure_keeps_supplied_observation_identity():
    obs=[dict(id='Q9',is_root=True,ref=dict(path='x.py',start_byte=1,end_byte=2))]
    result=analyze_source('def bad(:','python',root_name='bad',observations=obs)
    assert result['status']=='unknown'
    assert result['observations'][0]['id']=='Q9'


def test_body_import_rebinding_is_a_barrier():
    result=py('x = make()\nuse(x)\nimport different as x\nuse(x)')
    assert not result['groups']
    assert result['unknowns']


def test_augmented_assignment_does_not_claim_rhs_alias():
    result=py('x = make()\ny = other()\nx += y\nuse(x)\nuse(x)')
    assert result['bindings'][2]['previous_definition']=='B0'
    assert result['bindings'][2]['direct_rhs_binding'] is None


def test_adapter_revalidates_modified_owner_and_preserves_all_compact_qs():
    from prototypes.ordered_binding_history import analyze
    from relational_gap.frontend import extract_frontend,to_emitter_corpus
    from relation_search.compact_test_obligations import analyze as compact
    code='def test_case():\n    x=make()\n    assert use(x)==1\n    assert use(x)==2\n'
    frontend=extract_frontend([Source('test_example.py',code,'python')]); corpus=to_emitter_corpus(frontend)
    candidate=dict(id='c',base_test_id=next(iter(corpus['tests'])),edits=[],imports=[])
    graph=compact(corpus,frontend,candidate)
    result=analyze(corpus,frontend,candidate,source_analysis=graph)
    assert names(result)==['x']
    assert {q['id'] for q in result['observations']}==set(graph['obligations'])
    graph['sources'][graph['units'][graph['root']]['at']['source']]['code']='bad source'
    with pytest.raises(ValueError,match='mismatch'):
        analyze(corpus,frontend,candidate,source_analysis=graph)


def test_python_global_declaration_excludes_name_for_entire_root():
    result=py('global shared\nshared=make()\nuse(shared)\nother()\nuse(shared)')
    assert not result['groups']
    assert 'shared' in result['excluded_external_bindings']
    assert not any(b['name']=='shared' for b in result['bindings'])


def test_valid_python_nonlocal_root_never_treats_outer_cell_as_local():
    code='def outer():\n    shared=make()\n    def test_case():\n        nonlocal shared\n        shared=other()\n        use(shared)\n        mutate()\n        use(shared)\n'
    result=analyze_source(code,'python',root_name='test_case')
    assert not result['groups']
    assert 'shared' in result['excluded_external_bindings']


@pytest.mark.parametrize('language,code',[
    ('go','package p\nvar shared Object\nfunc TestCase() { shared=make(); use(shared); other(); use(shared) }'),
    ('typescript','let shared; function TestCase() { shared=make(); use(shared); other(); use(shared); }'),
])
def test_nonlocal_go_ts_assignment_cannot_establish_local_version(language,code):
    result=analyze_source(code,language,path='x.go' if language=='go' else 'x.ts',root_name='TestCase')
    assert not result['groups']
    assert any(u['reason']=='assignment_to_unproved_local_binding' for u in result['unknowns'])


@pytest.mark.parametrize('language,code',[
    ('python','def TestCase():\n    x=make()\n    def change():\n        nonlocal x\n        x=other()\n    x=make()\n    use(x)\n    change()\n    use(x)\n'),
    ('typescript','function TestCase() { let x=make(); const change=() => { x=other(); }; x=make(); use(x); change(); use(x); }'),
    ('go','package p\nfunc TestCase() { x:=make(); change:=func(){ x=other() }; x=make(); use(x); change(); use(x) }'),
])
def test_possible_closure_capture_never_rebuilds_a_false_stable_version(language,code):
    result=analyze_source(code,language,path={'python':'x.py','typescript':'x.ts','go':'x.go'}[language],root_name='TestCase')
    assert not result['groups']
    assert 'x' in result['excluded_possible_capture_bindings']


def test_decorated_python_root_recovered_with_decorator_unknown():
    code='@decorator\ndef test_case():\n    x=make()\n    use(x)\n    use(x)\n'
    source=Source('test_example.py',code,'python');root=source.root.named_children[0]
    result=analyze_source(code,'python',path=source.path,root_ref=dict(start_byte=root.start_byte,end_byte=root.end_byte))
    assert names(result)==['x']
    assert any(u['reason']=='root_decorator_behavior_unproved' for u in result['unknowns'])


def test_callback_test_extent_is_resolved_without_framework_name_rules():
    code='arbitraryRegistration("x", () => { let x=make(); use(x); use(x); });'
    source=Source('x.ts',code,'typescript');root=next(n for n in walk(source.root) if n.type=='call_expression')
    result=analyze_source(code,'typescript',path=source.path,root_ref=dict(start_byte=root.start_byte,end_byte=root.end_byte))
    assert names(result)==['x']


def test_go_address_escape_cannot_rebuild_local_version_after_barrier():
    code='package p\nfunc TestCase() { x:=make(); ptr:=&x; x=make(); use(x); replace(ptr); use(x) }'
    result=analyze_source(code,'go',path='x.go',root_name='TestCase')
    assert not result['groups']
    assert 'x' in result['excluded_address_taken_bindings']


def test_default_nested_helper_assertion_has_no_root_execution_phase():
    result=py('def helper():\n    assert observe()==1\nhelper()\nassert done()')
    assert len(result['observations'])==2
    assert result['observations'][0]['phase_statement'] is None
    assert result['observations'][0]['phase_status']=='helper_or_unmapped_phase_unknown'
    assert result['observations'][1]['phase_statement']=='S2'
