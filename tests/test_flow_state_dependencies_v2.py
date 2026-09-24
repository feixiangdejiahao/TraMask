"""Invented source only: may-state edges are provenance, not an alias proof."""

import pytest

from anchor_retrieval.index import Index
from anchor_retrieval.syntax import Source


def flow_for(code, language='python'):
    path = {'python': 'test_toy.py', 'go': 'toy_test.go',
            'typescript': 'toy.test.ts'}[language]
    source = Source(path, code, language)
    assert not source.root.has_error
    index = Index([source], '')
    unit = next(unit for unit in index.units.values() if unit.test)
    flow = index.flow(unit.id)
    # Nodes represent a one-pass may analysis; each dependency predates its use.
    assert all(dependency < node for node, dependencies in flow.edges.items()
               for dependency in dependencies)
    return flow


def observed_nodes(flow):
    assert len(flow.assertions) == 1
    return [flow.nodes[node] for node in sorted(flow.slice([flow.assertions[0].node]))]


@pytest.mark.parametrize('operation', ['mutate(value)', 'mutate(item=value)',
                                       'value.mutate()', 'mutate(value.item)',
                                       'mutate(value[0])'])
def test_unknown_receiver_or_argument_keeps_prior_mutation(operation):
    flow = flow_for('def test_toy():\n    value = make()\n    ' + operation +
                    '\n    assert observe(value) == 1\n')
    nodes = observed_nodes(flow)
    assert any(node['kind'] == 'call' and node['text'] == operation for node in nodes)
    assert any(node['kind'] == 'may_effect' and node['variable'] == 'value' for node in nodes)


def test_known_immutable_scalar_argument_does_not_gain_heap_effect():
    flow = flow_for('''def test_toy():
    value = 3
    unrelated(value)
    assert observe(value) == 1
''')
    assert not any(node['kind'] == 'call' and node['text'] == 'unrelated(value)'
                   for node in observed_nodes(flow))


@pytest.mark.parametrize('initial, target', [('[0]', 'value[0]'),
                                            ('make()', 'value.item'),
                                            ('make()', 'value.items[0]')])
def test_heap_assignment_reaches_later_whole_receiver_observation(initial, target):
    flow = flow_for('def test_toy():\n    value = ' + initial + '\n    ' + target +
                    ' = changed()\n    assert observe(value) == 1\n')
    nodes = observed_nodes(flow)
    written = next(node for node in nodes if node['kind'] == 'definition' and node['text'] == target)
    assert any(node['kind'] == 'call' and node['text'] == 'changed()' for node in nodes)
    assert any(flow.edge_kinds.get((node['id'], written['id'])) == 'may_effect'
               for node in nodes if node['kind'] == 'may_effect')


def test_subscript_address_dependencies_are_retained():
    flow = flow_for('''def test_toy():
    value = [0]
    position = select()
    value[position] = changed()
    assert observe(value) == 1
''')
    assert {'select()', 'changed()'} <= {node['text'] for node in observed_nodes(flow)
                                         if node['kind'] == 'call'}


@pytest.mark.parametrize('language, code, target', [
    ('go', '''package toy
import "testing"
func TestToy(t *testing.T) {
    value := []int{0}
    value[0] = changed()
    if subject(value) != 1 { t.Fatal("wrong") }
}
''', 'value[0]'),
    ('go', '''package toy
import "testing"
func TestToy(t *testing.T) {
    value := make()
    value.item = changed()
    if subject(value) != 1 { t.Fatal("wrong") }
}
''', 'value.item'),
    ('typescript', '''test('toy', () => {
    const value = [0];
    value[0] = changed();
    expect(subject(value)).toEqual(1);
});
''', 'value[0]'),
    ('typescript', '''test('toy', () => {
    const value = make();
    value.item = changed();
    expect(subject(value)).toEqual(1);
});
''', 'value.item'),
])
def test_go_and_typescript_heap_assignments_update_receiver(language, code, target):
    nodes = observed_nodes(flow_for(code, language))
    assert any(node['kind'] == 'definition' and node['text'] == target for node in nodes)
    assert any(node['kind'] == 'call' and node['text'] == 'changed()' for node in nodes)
    assert any(node['kind'] == 'may_effect' and node['variable'] == 'value' for node in nodes)


def test_go_var_initializers_bind_each_name_and_evaluate_calls_once():
    flow = flow_for('''package toy
import "testing"
func TestToy(t *testing.T) {
    var first, second int = one(), two()
    var plain int = 3
    const expected = 4
    if subject(first, second, plain) != expected { t.Fatal("wrong") }
}
''', 'go')
    nodes = observed_nodes(flow)
    assert {'first', 'second', 'plain'} <= {node['variable'] for node in nodes
                                           if node['kind'] == 'definition'}
    assert not any(node['kind'] == 'global' and node['text'] in {'first', 'second', 'plain'}
                   for node in nodes)
    assert [call.name for call in flow.calls].count('one') == 1
    assert [call.name for call in flow.calls].count('two') == 1
    assert 'expected' in flow.env


def test_go_uninitialized_var_still_has_a_local_definition():
    flow = flow_for('''package toy
import "testing"
func TestToy(t *testing.T) {
    var value int
    if subject(value) != 0 { t.Fatal("wrong") }
}
''', 'go')
    nodes = observed_nodes(flow)
    assert any(node['kind'] == 'implicit_zero' for node in nodes)
    assert any(node['kind'] == 'definition' and node['variable'] == 'value' for node in nodes)


@pytest.mark.parametrize('language, code, name', [
    ('python', '''def test_toy():
    inputs = [1, 2]
    for value in inputs:
        assert subject(value) == 2
''', 'value'),
    ('python', '''def test_toy():
    inputs = [(1, 2), (3, 4)]
    for key, value in inputs:
        assert subject(value) == 2
''', 'value'),
    ('go', '''package toy
import "testing"
func TestToy(t *testing.T) {
    inputs := []int{1, 2}
    for _, value := range inputs {
        if subject(value) != 2 { t.Fatal("wrong") }
    }
}
''', 'value'),
    ('go', '''package toy
import "testing"
func TestToy(t *testing.T) {
    inputs := []struct{ in int; want int }{{1, 2}, {3, 4}}
    for _, row := range inputs {
        if subject(row.in) != row.want { t.Fatal("wrong") }
    }
}
''', 'row'),
    ('typescript', '''test('toy', () => {
    const inputs = [1, 2];
    for (const value of inputs) {
        expect(subject(value)).toEqual(2);
    }
});
''', 'value'),
])
def test_iteration_variable_has_value_dependency_on_container(language, code, name):
    flow = flow_for(code, language)
    nodes = observed_nodes(flow)
    assert any(node['kind'] == 'definition' and node['variable'] == name for node in nodes)
    assert not any(node['kind'] == 'global' and node['text'] == name for node in nodes)
    iteration = next(node for node in nodes if node['kind'] == 'iteration')
    ancestors = flow.slice([iteration['id']])
    assert any(flow.nodes[node]['kind'] == 'definition' and flow.nodes[node]['variable'] == 'inputs'
               for node in ancestors)
    assert any(flow.edge_kinds[(iteration['id'], dependency)] == 'value'
               for dependency in flow.edges[iteration['id']])
