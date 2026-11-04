"""Local value-flow relations and retrieval features over parsed behavior.

Edges describe conditional static dependencies. A shared value source can attach
an operation to a later observation, but does not establish the operation's
effect, the observation's oracle, or execution of either event. Names are only
retrieval features; this module does not resolve cross-file method dispatch.
"""
from collections import defaultdict

from .behavior import _member_base
from .evidence import MEMBERS


def _ports(operation):
    return (operation['arguments']
            + ([operation['receiver']] if operation['receiver'] is not None else [])
            + ([operation['callee']] if operation['callee'] is not None else []))


def _field_path(graph, operation):
    start, end = operation['expression_range']
    node = graph.root.descendant_for_byte_range(start, end - 1)
    fields = []
    while node is not None and node.type in MEMBERS:
        field = next(node.child_by_field_name(name) for name in ('attribute', 'field', 'property')
                     if node.child_by_field_name(name) is not None)
        fields.append(graph.text(field))
        node = _member_base(node)
    return '.'.join(reversed(fields))


class RelationIndex:
    """Index one source; coordinates and definition IDs retain their provenance.

    ``operation_features[id]`` contains sorted ``related_operation_names``,
    ``receiver_constructors``, ``observation_fields`` and ``unknowns`` lists.
    A receiver constructor is its visible producing call, not an inferred type.
    ``edges`` retain the precise port/read and the evidence for each connection.
    """

    def __init__(self, graph, behavior):
        self.graph, self.behavior = graph, behavior
        self.source = graph.source['id']
        self.operations = {op['id']: op for op in behavior.operations}
        self.definitions = {item['id']: item for item in behavior.definitions}
        self.edges = []
        self.issues = list(behavior.issues)
        self.operation_features = {}
        self._children = defaultdict(set)
        self._uses = defaultdict(set)
        self._producers = defaultdict(set)
        self._unknowns = {key: set(op['unknowns']) for key, op in self.operations.items()}
        self._index_definitions()
        self._index_ports()
        self._index_features()

    def _edge(self, before, after, kind, evidence, *, certainty='static_dependency', unknowns=()):
        self.edges.append({'source': self.source, 'from': before, 'to': after,
                           'kind': kind, 'evidence': evidence, 'certainty': certainty,
                           'condition': 'if_reached_in_the_same_activation',
                           'unknowns': sorted(set(unknowns))})

    def _index_definitions(self):
        by_binding = defaultdict(list)
        for definition in self.definitions.values():
            by_binding[tuple(definition['binding'])].append(definition['id'])
        for op in self.operations.values():
            for identity in op['result']['definitions']:
                definition = self.definitions[identity]
                self._edge(op['id'], identity, 'result_definition',
                           {'result_range': op['expression_range'], 'definition_range': definition['range']},
                           unknowns=definition['unknowns'])
                value = definition['value_identity']
                if value is not None:
                    self._producers[value].add(op['id'])
        for definition in self.definitions.values():
            for previous in definition['source_versions']:
                self._edge(previous, definition['id'], 'reference_assignment',
                           {'range': definition['range']}, unknowns=definition['unknowns'])
            # Input dependence is distinct from object identity. A constructor
            # can depend on a schema without returning that schema object.
            value = self.behavior._definition_values.get(definition['id'])
            if value is None:
                continue
            statement = definition['statement']
            for read in self.behavior._identifier_reads[statement]:
                if not (value.start_byte <= read.start_byte and read.end_byte <= value.end_byte):
                    continue
                binding = self.graph._binding(self.graph.nodes[statement]['scope'], self.graph.text(read))
                versions = self.behavior._versions(statement, read.start_byte, binding)
                lexical = binding[0] != self.graph.nodes[statement]['scope']
                if lexical:
                    versions = set(by_binding[binding])
                for previous in sorted(versions - {definition['id']}):
                    self._edge(previous, definition['id'], 'construction_input',
                               {'read_range': [read.start_byte, read.end_byte],
                                'value_range': [value.start_byte, value.end_byte],
                                'use': 'callable' if read.parent.type in {'call', 'call_expression', 'new_expression'}
                                and read.parent.child_by_field_name('function') == read else 'value'},
                               certainty='may_lexical_definition' if lexical else 'static_dependency',
                               unknowns=definition['unknowns'])
        captured = {tuple(read['binding']) for op in self.operations.values()
                    for port in _ports(op) for read in port['reads']
                    if read['binding'] is not None and read['binding'][0] != op['scope']}
        for binding in sorted(captured):
            cell = f'{self.source}:cell:{binding[0]}:{binding[1]}'
            for identity in by_binding[binding]:
                self._edge(identity, cell, 'lexical_cell_definition',
                           {'binding': list(binding)}, certainty='may_lexical_definition',
                           unknowns=['value_at_captured_frame_invocation_not_established'])

    def _index_ports(self):
        by_statement = defaultdict(list)
        for op in self.operations.values():
            by_statement[op['statement']].append(op)
        for op in self.operations.values():
            for port in _ports(op):
                self._unknowns[op['id']].update(port['unknowns'])
                reads = {tuple(read['range']): read for read in port['reads']}
                if port['binding'] is not None:
                    reads[tuple(port['range'])] = port
                for read in reads.values():
                    self._unknowns[op['id']].update(read['unknowns'])
                    evidence = {'port': port['role'], 'port_range': port['range'],
                                'read_range': read['range'], 'binding': read['binding'],
                                'value_identity': read['value_identity']}
                    kind = ('definition_to_observation' if op['observation'] is not None else
                            'definition_to_member' if op['kind'].startswith('member_') else
                            'definition_to_port')
                    for identity in read['definition_versions']:
                        self._edge(identity, op['id'], kind, evidence,
                                   certainty=('static_dependency' if len(read['definition_versions']) == 1
                                              else 'may_reaching_definition'),
                                   unknowns=read['unknowns'])
                    if read['value_identity'] is not None:
                        self._uses[read['value_identity']].add(op['id'])
                    elif not read['definition_versions'] and read['binding'] is not None:
                        scope, name = read['binding']
                        self._edge(f'{self.source}:cell:{scope}:{name}', op['id'],
                                   'unresolved_binding_use', evidence, certainty='unresolved',
                                   unknowns=read['unknowns'])
                # A compound assertion has no exact producer port. Its maximal
                # contained operations still contribute operands in this frame.
                start, end = port['range']
                children = sorted((other for other in by_statement[op['statement']]
                                   if other['id'] != op['id'] and other['scope'] == op['scope']
                                   and start <= other['expression_range'][0]
                                   and other['expression_range'][1] <= end),
                                  key=lambda other: (other['expression_range'][0],
                                                     -other['expression_range'][1]))
                last_end = -1
                for child in children:
                    a, b = child['expression_range']
                    if b <= last_end:
                        continue
                    last_end = b
                    self._children[op['id']].add(child['id'])
                    self._edge(child['id'], op['id'],
                               'operand_value' if [a, b] == port['range'] else 'operand_contribution',
                               {'port': port['role'], 'port_range': port['range'], 'producer_range': [a, b]},
                               unknowns=child['unknowns'])
            for guard in op['guards']:
                statement = guard['statement']
                a, b = guard['range']
                for read in self.behavior._identifier_reads[statement]:
                    if not (a <= read.start_byte and read.end_byte <= b):
                        continue
                    binding = self.graph._binding(self.graph.nodes[statement]['scope'], self.graph.text(read))
                    versions = self.behavior._versions(statement, read.start_byte, binding)
                    for identity in sorted(versions):
                        self._edge(identity, op['id'], 'guard_definition',
                                   {'port': 'guard:' + str(guard['polarity']), 'range': guard['range']},
                                   certainty='may_reaching_definition' if len(versions) > 1 else 'static_dependency')

    def _index_features(self):
        receivers, fields, names = {}, {}, {}
        callee_ranges = {tuple(op['callee']['range']) for op in self.operations.values()
                         if op['callee'] is not None}
        # A member write's value lies outside its left-hand expression range.
        # Order by operand dependencies, not by expression length or position.
        ordered, seen = [], set()
        for key in self.operations:
            pending = [(key, False)]
            while pending:
                current, ready = pending.pop()
                if current in seen:
                    continue
                if ready:
                    seen.add(current)
                    ordered.append(current)
                else:
                    pending.append((current, True))
                    pending.extend((child, False) for child in sorted(self._children[current]))
        for key in ordered:
            op = self.operations[key]
            receivers[key], fields[key] = set(), set()
            names[key] = {op['name']} if op['name'] and op['kind'] in {'call', 'assert'} else set()
            receiver = op['receiver']
            if receiver is not None and receiver['value_identity'] is not None:
                receivers[key].add(receiver['value_identity'])
            for child in self._children[key]:
                receivers[key].update(receivers[child])
                fields[key].update(fields[child])
                names[key].update(names[child])
            if receiver is not None and not receivers[key]:
                self._unknowns[key].add('receiver_value_not_established')
            if op['kind'] == 'member_read' and tuple(op['expression_range']) not in callee_ranges:
                path = _field_path(self.graph, op)
                fields[key].update((value, path) for value in (receivers[key] or {None}))

        # Reaching-value tokens connect aliases, but never equal variable names
        # after rebinding. Two different call-result tokens are not must-distinct.
        constructors = {key: set() for key in self.operations}
        for key, values in receivers.items():
            for value in values:
                for producer in self._producers[value]:
                    name = self.operations[producer]['name']
                    if name:
                        constructors[key].add(name)
                        names[key].add(name)
        initial_names = {key: set(values) for key, values in names.items()}
        for value, producers in self._producers.items():
            for producer in producers:
                for consumer in self._uses[value]:
                    names[consumer].update(initial_names[producer])
                    names[producer].update(initial_names[consumer])

        observed_fields = {key: set() for key in self.operations}
        receiver_calls = defaultdict(set)
        for key, values in receivers.items():
            op = self.operations[key]
            if op['kind'] == 'call' and op['observation'] is None:
                for value in values:
                    receiver_calls[op['scope'], value].add(key)
        for key, observation in self.operations.items():
            if observation['observation'] is None:
                continue
            observed_fields[key].update(path for _, path in fields[key])
            by_value = defaultdict(set)
            for value, path in fields[key]:
                if value is not None:
                    by_value[value].add(path)
            for value, paths in by_value.items():
                for related in sorted(receiver_calls[observation['scope'], value]):
                    op = self.operations[related]
                    if op['expression_range'][0] >= observation['expression_range'][0]:
                        continue
                    unknowns = ['operation_effect_on_observed_field_not_established',
                                'relative_execution_not_established']
                    self._edge(related, key, 'operation_observation_candidate',
                               {'value_identity': value, 'observed_fields': sorted(paths),
                                'operation_guards': op['guards'], 'observation_guards': observation['guards'],
                                'operation_frames': op['frames'], 'observation_frames': observation['frames']},
                               certainty='candidate', unknowns=unknowns)
                    observed_fields[related].update(paths)
                    names[key].update(initial_names[related])
                    names[related].update(initial_names[key])
                    self._unknowns[related].update(unknowns)
                    self._unknowns[key].update(unknowns)
        for key in self.operations:
            self.operation_features[key] = {
                'related_operation_names': sorted(names[key]),
                'receiver_constructors': sorted(constructors[key]),
                'observation_fields': sorted(observed_fields[key]),
                'unknowns': sorted(self._unknowns[key]),
            }

    def view(self, operation_ids, definition_ids=()):
        operations = set(operation_ids)
        selected = operations | set(definition_ids)
        return {'source': self.source,
                'edges': [edge for edge in self.edges if edge['from'] in selected or edge['to'] in selected],
                'operation_features': {key: self.operation_features[key] for key in sorted(operations)},
                'issues': self.issues,
                'interpretation': 'static_dependencies_and_retrieval_candidates_not_semantic_equivalence'}
