"""Endpoint groups preserve branches while avoiding unrelated test scopes."""
from eviweave.evidence import SourceGraph
from eviweave.slice_frontier import frontier_groups,validation_groups,source_syntax
from eviweave.slicing import ContextProgram
from types import SimpleNamespace


def seed_at(graph,text):
    start=graph.raw.index(text.encode())
    return graph.criterion(start,start+len(text))['node']


def test_two_observations_of_one_operation_keep_both_endpoints():
    graph=SourceGraph({'id':'sample','path':'test.py','raw':b'''def test_value(flag):
    result = operation()
    if flag:
        assert result == 3
    else:
        print(result)
    unrelated = 99
'''})
    seed=seed_at(graph,'operation()');groups=frontier_groups(graph,[seed]);assert len(groups)==1
    ends=groups[0]['frontier'];assert len(ends)==2
    retained={n for end in ends for n in graph.slice(end,forward=False)['nodes']}
    assert set(graph.slice(seed)['nodes'])<=retained
    assert all('unrelated' not in graph.text(graph.nodes[n]['ast']) for n in retained if n!=0)


def test_independent_functions_remain_separate_even_with_equal_helper_names():
    graph=SourceGraph({'id':'sample','path':'test.py','raw':b'''def first():
    x = helper(1)
    assert x == 2
def second():
    y = helper(3)
    assert y == 4
'''})
    groups=frontier_groups(graph,[seed_at(graph,'helper(1)'),seed_at(graph,'helper(3)')])
    assert len(groups)==2 and groups[0]['scope']!=groups[1]['scope']
    assert all(len(g['frontier'])==1 for g in groups)


def test_loop_dependency_component_retains_a_nonempty_frontier():
    graph=SourceGraph({'id':'sample','path':'test.py','raw':b'''def test_values(values):
    total = 0
    for value in values:
        total += transform(value)
    assert total == 3
'''})
    seed=seed_at(graph,'transform(value)');groups=frontier_groups(graph,[seed])
    retained={n for group in groups for end in group['frontier'] for n in graph.slice(end,forward=False)['nodes']}
    assert groups and all(g['frontier'] for g in groups)
    assert set(graph.slice(seed)['nodes'])<=retained


def test_module_statements_do_not_receive_autouse_test_fixture_setup(tmp_path):
    raw=b'''import pytest
@pytest.fixture(autouse=True)
def setup_value():
    return 7
module_value = 3
print(module_value)
'''
    source='sample';path='/app/test_sample.py';digest='sample-digest'
    graph=SourceGraph({'id':source,'path':path,'raw':raw})
    trajectory=SimpleNamespace(path=tmp_path/'materials.json',materials={source:{'path':path,'sha256':digest,'kind':'file'}})
    context={'execution':None,'source_versions':{path:[source]},'input_versions':{},
             'source_basis':{},'unresolved_versions':{},'unresolved_bytecode_sources':[]}
    program=ContextProgram(trajectory.materials,context,{(path,digest):graph},lambda info:(raw,None))
    view=program.slice(source,seed_at(graph,'module_value = 3'))
    assert view['files'] and not any(c['kind']=='framework_setup' for c in view['calls'])


def test_test_frontier_keeps_independent_conditions_inside_one_test_together():
    raw=b'''def test_combination():
    set_global_mode(True)
    value = query()
    assert value == 3
def test_another():
    value = query()
    assert value == 5
'''
    graph=SourceGraph({'id':'sample','path':'test_sample.py','raw':raw})
    seeds=[seed_at(graph,text) for text in ('set_global_mode(True)','query()','assert value == 5')]
    groups=validation_groups(graph,seeds)
    assert len(groups)==2
    assert sorted(len(g['matches']) for g in groups)==[1,2]


def test_multi_seed_view_equals_union_and_keeps_argument_bindings(tmp_path):
    raw=b'''def helper(value):
    return value * 2
def test_pair():
    left = helper(3)
    right = helper(7)
    assert left == 6
    assert right == 14
'''
    source='sample';path='/app/test_pair.py';digest='sample-digest'
    graph=SourceGraph({'id':source,'path':path,'raw':raw})
    trajectory=SimpleNamespace(path=tmp_path/'materials.json',materials={source:{'path':path,'sha256':digest,'kind':'file'}})
    context={'execution':None,'source_versions':{path:[source]},'input_versions':{},
             'source_basis':{},'unresolved_versions':{},'unresolved_bytecode_sources':[]}
    program=ContextProgram(trajectory.materials,context,{(path,digest):graph},lambda info:(raw,None))
    seeds=[(source,seed_at(graph,text)) for text in ('assert left == 6','assert right == 14')]
    individual=[program.slice(*seed) for seed in seeds];joint=program.slice_many(seeds)
    expected={(f['material'],n) for view in individual for f in view['files'] for n in f['nodes']}
    assert expected=={(f['material'],n) for f in joint['files'] for n in f['nodes']}
    assert {c['arguments'][0]['parameter'] for c in joint['calls']}=={'value'}


def test_rust_function_slice_preserves_execution_attributes():
    graph=SourceGraph({'id':'sample','path':'tests.rs','raw':b'''#[cfg(feature = "jobs")]
#[test]
fn promise() {
    run_jobs();
}
'''})
    result=graph.slice(seed_at(graph,'run_jobs()'))
    selected=b''.join(graph.raw[a:b] for a,b in result['ranges'])
    assert b'#[test]' in selected and b'#[cfg(feature = "jobs")]' in selected


def test_typescript_type_check_and_throw_callback_follow_the_target(tmp_path):
    raw=b'''test('schema', () => {
    const output = parseSchema(input)
    const typed: Equal<typeof output, Expected> = 1
    typed
    expect(() => output.parse(undefined)).toThrow()
})
'''
    source='sample';path='/app/schema.test.ts';digest='sample-digest'
    graph=SourceGraph({'id':source,'path':path,'raw':raw})
    trajectory=SimpleNamespace(path=tmp_path/'materials.json',materials={source:{'path':path,'sha256':digest,'kind':'file'}})
    context={'execution':None,'source_versions':{path:[source]},'input_versions':{},
             'source_basis':{},'unresolved_versions':{},'unresolved_bytecode_sources':[]}
    program=ContextProgram(trajectory.materials,context,{(path,digest):graph},lambda info:(raw,None))
    view=program.slice(source,seed_at(graph,'parseSchema(input)'))
    selected={n for file in view['files'] for n in file['nodes']}
    assert seed_at(graph,'const typed: Equal<typeof output, Expected> = 1') in selected
    assert seed_at(graph,'expect(() => output.parse(undefined)).toThrow()') in selected


def test_go_named_function_value_recovers_its_caller(tmp_path):
    raw=b'''package sample
func TestErrors(t *testing.T) {
    run := func(value int) int { return transform(value) }
    result := run(3)
    if result != 6 { t.Errorf("wrong result") }
}
'''
    source='sample';path='/app/errors_test.go';digest='sample-digest'
    graph=SourceGraph({'id':source,'path':path,'raw':raw})
    trajectory=SimpleNamespace(path=tmp_path/'materials.json',materials={source:{'path':path,'sha256':digest,'kind':'file'}})
    context={'execution':None,'source_versions':{path:[source]},'input_versions':{},
             'source_basis':{},'unresolved_versions':{},'unresolved_bytecode_sources':[]}
    program=ContextProgram(trajectory.materials,context,{(path,digest):graph},lambda info:(raw,None))
    view=program.slice(source,seed_at(graph,'transform(value)'))
    selected={n for file in view['files'] for n in file['nodes']}
    assert seed_at(graph,'result := run(3)') in selected
    assert seed_at(graph,'t.Errorf("wrong result")') in selected


def test_python_version_syntax_keeps_lexical_group_and_reports_boundary_issue():
    raw=b"def test_legacy():\n    print 'legacy'\n    operation()\n"
    graph=SourceGraph({'id':'legacy','path':'legacy_test.py','raw':raw})
    groups=validation_groups(graph,[seed_at(graph,'operation()')])
    assert groups[0]['boundary'][0]=='scope'
    assert groups[0]['boundary_issue']['status']=='unresolved'
    assert not graph.issues


def test_go_index_increment_reaches_assertion_and_keeps_deferred_cleanup(tmp_path):
    raw=b'''package sample
func TestErrors(t *testing.T) {
    defer cleanup()
    counts := make(map[string]int)
    err := operation()
    counts[err.Error()]++
    expected := []string{"injected"}
    for _, key := range expected {
        if counts[key] == 0 { t.Errorf("missing error") }
    }
}
'''
    source='sample';path='/app/errors_test.go';digest='sample-digest'
    graph=SourceGraph({'id':source,'path':path,'raw':raw})
    trajectory=SimpleNamespace(path=tmp_path/'materials.json',materials={source:{'path':path,'sha256':digest,'kind':'file'}})
    context={'execution':None,'source_versions':{path:[source]},'input_versions':{},
             'source_basis':{},'unresolved_versions':{},'unresolved_bytecode_sources':[]}
    program=ContextProgram(trajectory.materials,context,{(path,digest):graph},lambda info:(raw,None))
    view=program.slice(source,seed_at(graph,'operation()'))
    selected={n for file in view['files'] for n in file['nodes']}
    assert seed_at(graph,'t.Errorf("missing error")') in selected
    assert seed_at(graph,'defer cleanup()') in selected


def test_scope_syntax_keeps_empty_callback_braces_and_python_docstring():
    raw=b"test('value', () => { const value = operation(() => {}); expect(value).toBe(3); });"
    graph=SourceGraph({'id':'js','path':'value.test.js','raw':raw})
    view=graph.slice(seed_at(graph,'operation(() => {})'))
    ranges=source_syntax(graph,view['nodes'],view['ranges'])
    retained=bytearray(b' '*len(raw))
    for a,b in ranges:retained[a:b]=raw[a:b]
    assert not SourceGraph({'id':'retained','path':'retained.js','raw':bytes(retained)}).root.has_error
    raw=b'def test_value():\n    """Exercises the public promise."""\n    assert operation() == 3\n'
    graph=SourceGraph({'id':'py','path':'test_value.py','raw':raw});view=graph.slice(seed_at(graph,'operation()'))
    ranges=source_syntax(graph,view['nodes'],view['ranges'])
    assert b'"""Exercises the public promise."""' in b''.join(raw[a:b] for a,b in ranges)
