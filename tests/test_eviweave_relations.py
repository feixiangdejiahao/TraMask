"""Relation evidence is exercised with real source parsers and value changes."""
import json
import subprocess
import sys

from eviweave.behavior import BehaviorIndex
from eviweave.evidence import SourceGraph
from eviweave.relations import RelationIndex


def index(text, suffix='.py'):
    graph = SourceGraph({'id': 'source', 'path': 'source' + suffix, 'raw': text.encode()})
    assert not graph.issues
    behavior = BehaviorIndex(graph)
    return behavior, RelationIndex(graph, behavior)


def call(behavior, name):
    return next(op for op in behavior.operations if op['kind'] == 'call' and op['name'] == name)


def test_nested_consumer_retains_receiver_and_later_field_observation():
    behavior, relations = index('response = Response(body)\nparts = list(response.iter_multipart())\n'
                                'assert response.is_closed is True\n')
    consumer, producer = call(behavior, 'list'), call(behavior, 'iter_multipart')
    observation = next(op for op in behavior.operations if op['kind'] == 'assert')
    assert any(edge['from'] == producer['id'] and edge['to'] == consumer['id']
               and edge['kind'] == 'operand_value' for edge in relations.edges)
    attached = next(edge for edge in relations.edges if edge['from'] == consumer['id']
                    and edge['to'] == observation['id'] and edge['kind'] == 'operation_observation_candidate')
    assert attached['certainty'] == 'candidate'
    assert attached['evidence']['observed_fields'] == ['is_closed']
    assert 'operation_effect_on_observed_field_not_established' in attached['unknowns']
    features = relations.operation_features[consumer['id']]
    assert {'list', 'iter_multipart', 'Response'} <= set(features['related_operation_names'])
    assert features['receiver_constructors'] == ['Response']
    assert features['observation_fields'] == ['is_closed']


def test_print_and_assert_keep_observed_field_and_result_provenance():
    behavior, relations = index('result = converter.structure(data)\nprint("value:", result.value)\n'
                                'assert result.value is None\n')
    producer = call(behavior, 'structure')
    definition = producer['result']['definitions'][0]
    observations = [op for op in behavior.operations if op['observation'] is not None]
    assert len(observations) == 2
    for observation in observations:
        features = relations.operation_features[observation['id']]
        assert features['observation_fields'] == ['value']
        assert 'structure' in features['related_operation_names']
        assert any(edge['from'] == definition and edge['to'] == observation['id']
                   and edge['kind'] == 'definition_to_observation' for edge in relations.edges)


def test_returned_object_fields_follow_result_definition_not_receiver_identity():
    behavior, relations = index('function f(reporter) { const report = reporter.getReport();\n'
                                'expect(report.count).toBe(3); }', '.js')
    producer = call(behavior, 'getReport')
    definition = producer['result']['definitions'][0]
    member = next(op for op in behavior.operations if op['kind'] == 'member_read' and op['name'] == 'count')
    assert any(edge['from'] == definition and edge['to'] == member['id']
               and edge['kind'] == 'definition_to_member' for edge in relations.edges)
    assert member['receiver']['value_identity'] != producer['receiver']['value_identity']
    check = call(behavior, 'toBe')
    assert relations.operation_features[check['id']]['observation_fields'] == ['count']
    assert 'getReport' in relations.operation_features[check['id']]['related_operation_names']
    assert not any(edge['kind'] == 'reference_assignment' for edge in relations.edges)


def test_rebinding_does_not_connect_an_old_operation_to_a_new_objects_field():
    text = '''class Box:
    def __init__(self):
        self.closed = False
    def close(self):
        self.closed = True
box = Box()
old = box
box.close()
box = Box()
assert not box.closed
assert old.closed
'''
    subprocess.run([sys.executable, '-c', text], check=True, capture_output=True)
    behavior, relations = index(text)
    operation = call(behavior, 'close')
    observations = [op for op in behavior.operations if op['kind'] == 'assert']
    attached = [edge for edge in relations.edges if edge['from'] == operation['id']
                and edge['kind'] == 'operation_observation_candidate']
    assert [edge['to'] for edge in attached] == [observations[1]['id']]
    assert any(edge['kind'] == 'reference_assignment' for edge in relations.edges)


def test_callback_mutation_retains_unknown_value_without_binding_to_registration():
    behavior, relations = index('def run():\n result = None\n def callback(value):\n'
                                '  nonlocal result\n  result = value\n register(callback)\n'
                                ' assert result.error is None\n')
    observation = next(op for op in behavior.operations if op['kind'] == 'assert')
    edges = [edge for edge in relations.edges if edge['to'] == observation['id']]
    assert any(edge['kind'] == 'unresolved_binding_use' for edge in edges)
    assert not any(edge['kind'] == 'definition_to_observation' for edge in edges)
    assert 'lexical_cell_can_be_rebound_by_another_frame' in relations.operation_features[observation['id']]['unknowns']
    assert relations.operation_features[observation['id']]['observation_fields'] == ['error']
    assert not any(edge['kind'] == 'operation_observation_candidate' for edge in edges)


def test_branch_join_retains_multiple_reaching_definitions_as_may_relations():
    behavior, relations = index('def f(flag):\n if flag:\n  result = first()\n else:\n'
                                '  result = second()\n assert result.value\n')
    observation = next(op for op in behavior.operations if op['kind'] == 'assert')
    edges = [edge for edge in relations.edges if edge['to'] == observation['id']
             and edge['kind'] == 'definition_to_observation']
    assert len(edges) == 2
    assert {edge['certainty'] for edge in edges} == {'may_reaching_definition'}
    assert not any(edge['kind'] == 'operation_observation_candidate' for edge in relations.edges)


def test_member_write_has_an_operand_outside_its_left_hand_expression():
    behavior, relations = index('function f(obj) { obj.result = new Result(obj.input); }', '.js')
    write = next(op for op in behavior.operations if op['kind'] == 'member_write')
    producer = call(behavior, 'Result')
    assert any(edge['from'] == producer['id'] and edge['to'] == write['id']
               and edge['kind'] == 'operand_value' for edge in relations.edges)
    assert 'Result' in relations.operation_features[write['id']]['related_operation_names']


def test_matching_method_name_does_not_resolve_a_receiver_or_cross_frame_return():
    behavior, relations = index('class Reporter { getReport() { return { count: 3 }; } }\n'
                                'class App { read() { return this.reporter.getReport(); } }', '.js')
    operation = call(behavior, 'getReport')
    assert 'receiver_value_not_established' in relations.operation_features[operation['id']]['unknowns']
    assert not any(edge['kind'] == 'result_definition' and edge['from'] == operation['id']
                   for edge in relations.edges)
    assert not any(edge['kind'] == 'operation_observation_candidate' for edge in relations.edges)


def test_parse_issue_is_preserved_and_view_is_serializable():
    graph = SourceGraph({'id': 'broken', 'path': 'broken.py', 'raw': b'def f('})
    relations = RelationIndex(graph, BehaviorIndex(graph))
    assert relations.view([])['issues'] == graph.issues
    behavior, relations = index('x = make()\nconsume(x)\n')
    selected = call(behavior, 'consume')['id']
    view = json.loads(json.dumps(relations.view([selected])))
    assert view['edges']
    assert list(view['operation_features']) == [selected]
