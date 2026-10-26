"""Ranking tests use synthetic repositories and no execution or reference data."""
from collections import defaultdict

from anchor_retrieval.syntax import Source, child, walk
from generic_composition.corpus import build_corpus
from generic_composition.terms import from_source
from prototypes.test_edit_analogy_v02.generate import _binding_labels
from prototypes.observation_guided_test_analogy.core import _features, edit_priority, rank_neighbors, target_priority


PRELUDE = '''from sample_api import left, right
class Box:
    def left(self): return 1
    def right(self): return 2
    def bump(self): pass
def prepare(): return 7
def normalize(value): return value
def observe(value): return value
'''


def corpus(tmp_path, bodies):
    code = PRELUDE + '\n'.join(f'def test_{name}():\n    ' + body.replace('\n', '\n    ')
                              for name, body in bodies.items()) + '\n'
    (tmp_path / 'test_priority.py').write_text(code)
    data = build_corpus(tmp_path, 'python')
    source = Source('test_priority.py', code, 'python')
    records, facts = {}, defaultdict(list)
    for item in data['capsules']:
        facts[item['test_id']].append(item)
    for test in data['tests'].values():
        node = next(n for n in walk(source.root) if n.type == 'function_definition'
                    and n.start_byte == test['definition_span']['start_byte'])
        body = child(node, 'body')
        converted = from_source(source, body)
        records[test['name'].removeprefix('test_')] = {
            'test': test, 'instance_id': test['id'], 'tree': converted,
            'bindings': _binding_labels(source, body, converted, test['parameters'])}
    return records, facts


def features(records, facts, name):
    record = records[name]
    return _features(record, facts[record['test']['id']])


def test_same_factory_is_not_same_observation_when_field_or_method_differs(tmp_path):
    records, facts = corpus(tmp_path, {
        'A': 'box = Box()\nassert box.left() == 1',
        'same': 'box = Box()\nassert box.left() == 99',
        'different': 'box = Box()\nassert box.right() == 99',
    })
    A = features(records, facts, 'A')
    # This corpus conservatively leaves receiver dispatch unresolved.
    assert target_priority(A, features(records, facts, 'same')) == 1
    assert target_priority(A, features(records, facts, 'different')) == 0
    incoming = [records['different'], records['same']]
    output = rank_neighbors(records['A'], incoming, capsules=facts, phase='target')
    assert output == list(reversed(incoming))


def test_resolved_observer_identity_ranks_above_spelling_only_matches(tmp_path):
    records, facts = corpus(tmp_path, {
        'A': 'box = Box()\nassert left(box) == 1',
        'same': 'renamed = Box()\nassert left(renamed) == 99',
        'different': 'box = Box()\nassert right(box) == 99',
    })
    A = features(records, facts, 'A')
    assert target_priority(A, features(records, facts, 'same')) == 2
    assert target_priority(A, features(records, facts, 'different')) == 0


def test_plain_field_projection_separates_shared_factory_results(tmp_path):
    records, facts = corpus(tmp_path, {
        'A': 'box = Box()\nassert box.left == 1',
        'same': 'box = Box()\nassert box.left == 777',
        'different': 'box = Box()\nassert box.right == 777',
    })
    A = features(records, facts, 'A')
    assert target_priority(A, features(records, facts, 'same')) > 0
    assert target_priority(A, features(records, facts, 'different')) == 0


def test_unrelated_added_assignment_is_below_value_connected_operation(tmp_path):
    records, facts = corpus(tmp_path, {
        'A': 'box = Box()\nassert box.left() == 1',
        'unrelated': 'box = Box()\nunused = prepare()\nassert box.left() == 1',
        'value': 'box = Box()\nassert normalize(box.left()) == 1',
    })
    A = features(records, facts, 'A')
    assert edit_priority(A, features(records, facts, 'unrelated'))['score'] == 0
    assert edit_priority(A, features(records, facts, 'value'))['kind'] == 'value'
    output = rank_neighbors(records['A'], [records['unrelated'], records['value']], capsules=facts, phase='edit')
    assert output == [records['value'], records['unrelated']]


def test_state_operation_with_only_may_effect_path_is_not_called_value_dependence(tmp_path):
    records, facts = corpus(tmp_path, {
        'A': 'box = Box()\nassert box.left() == 1',
        'B': 'box = Box()\nbox.bump()\nassert box.left() == 1',
    })
    priority = edit_priority(features(records, facts, 'A'), features(records, facts, 'B'))
    assert priority['kind'] == 'may_effect'
    assert priority['score'] == 2
    assert priority['new_observations'] == 0
    reverse = edit_priority(features(records, facts, 'B'), features(records, facts, 'A'))
    assert reverse['kind'] == 'may_effect'
    assert reverse['changed_calls'][0]['side'] == 'A_deleted_or_changed'


def test_unknown_argument_type_adds_only_may_effect_and_remains_in_neighbors(tmp_path):
    records, facts = corpus(tmp_path, {
        'A': 'value = unknown_factory()\nassert observe(value) == 1',
        'B': 'value = unknown_factory()\nmystery(value)\nassert observe(value) == 1',
    })
    priority = edit_priority(features(records, facts, 'A'), features(records, facts, 'B'))
    # Unknown argument types now retain an explicit possible mutation edge.
    # This improves search provenance, without becoming a value-dependence or
    # semantic-admission proof: score 2 is may-effect, while value is score 3.
    assert priority['kind'] == 'may_effect'
    assert priority['score'] == 2
    assert priority['new_observations'] == 0
    assert all(call['connection'] == 2 for call in priority['changed_calls'])
    capsule = facts[records['B']['test']['id']][0]
    graph = capsule['bindings']
    mystery = next(node for node in graph['slice_nodes'] if node['kind'] == 'call' and node['call'] == 'mystery')
    assert any(edge['kind'] == 'may_effect' and edge['to'] == mystery['id'] for edge in graph['slice_edges'])
    assert graph['alias_precision'] == 'unknown'
    assert 'mystery' in graph['unknown_effects']
    assert 'call_effects_and_aliases_not_proved' in capsule['unknowns']
    assert rank_neighbors(records['A'], [records['B']], capsules=facts, phase='edit') == [records['B']]


def test_expected_expression_change_does_not_create_an_actual_observation(tmp_path):
    records, facts = corpus(tmp_path, {
        'A': 'box = Box()\nassert box.left() == 1',
        'B': 'box = Box()\nassert box.left() == prepare()',
        'constant': 'box = Box()\nassert box.left() == 999',
    })
    A = features(records, facts, 'A')
    assert A['keys'] == features(records, facts, 'B')['keys'] == features(records, facts, 'constant')['keys']
    assert edit_priority(A, features(records, facts, 'B'))['score'] == 0
    assert edit_priority(A, features(records, facts, 'constant'))['score'] == 0


def test_ordering_is_stable_and_keeps_every_unknown_or_unrelated_neighbor(tmp_path):
    records, facts = corpus(tmp_path, {
        'A': 'assert unknown(1) == 2',
        'B': 'assert another(1) == 2',
        'C': 'assert third(1) == 2',
    })
    incoming = [records['C'], records['B']]
    assert rank_neighbors(records['A'], incoming, capsules=facts, phase='target') == incoming
    assert rank_neighbors(records['A'], incoming, capsules=facts, phase='edit') == incoming
