"""Port-connected admission witnesses over conditional static behavior.

Candidate keys identify a corresponding role, not equal state. Source-backed
endpoints and parameter values remain available after comparison sharing.
"""
from collections import defaultdict
from decimal import Decimal
from itertools import combinations
import re

from .alignment import TermIndex, term_key
from .alignment_templates import NUMBERS, callee_members, term_template, typed_reporting_values
from .behavior import FRESH, REFERENCE_LANGUAGES, SUBSCRIPTS
from .relational_alignment import digest, identity_relation, ports
from .relations import RelationIndex


def literal_number(term):
    if term.kind in NUMBERS:
        value = term.value.replace('_', '')
        if term.kind == 'int_literal' and re.fullmatch(r'0[0-7]+', value):
            return Decimal(int(value, 8))
        if re.fullmatch(r'0[xX][0-9a-fA-F]+', value):
            return Decimal(int(value, 16))
        if re.fullmatch(r'0[bB][01]+', value):
            return Decimal(int(value, 2))
        if re.fullmatch(r'0[oO][0-7]+', value):
            return Decimal(int(value, 8))
        if re.fullmatch(r'(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?', value):
            return Decimal(value)
    if term.kind in {'unary_expression', 'unary_operator'}:
        operands = [literal_number(child) for _, child in term.children if child.kind in NUMBERS]
        operators = [child.value for _, child in term.children if child.value in {'-', '+'}]
        if len(operands) == len(operators) == 1 and operands[0] is not None:
            return -operands[0] if operators[0] == '-' else operands[0]
    return None


class PortAdmissionIndex:
    def __init__(self, sources, selected):
        self.sources = sources
        self.operations = {}
        self.definitions = {}
        self.terms = {}
        self.incoming, self.outgoing = defaultdict(list), defaultdict(list)
        self.by_statement = defaultdict(list)
        self.definition_producers = {}
        self.reporting = typed_reporting_values(sources)
        self.references = {}
        self.observation_fields = {}
        self.receiver_users = defaultdict(list)
        self.descriptors, self.features = {}, {}
        self.tracking_counts = defaultdict(int)
        for source, (graph, behavior) in sources.items():
            self.terms[source] = TermIndex(graph)
            for op in behavior.operations:
                self.operations[source, op['id']] = op
                if op['receiver'] is not None:
                    receiver = op['receiver']
                    value = receiver['value_identity']
                    binding = tuple(receiver['binding']) if receiver['binding'] is not None else None
                    token = ('value', value) if value is not None else ('cell', binding) if binding is not None else None
                    if token is not None:
                        self.receiver_users[source, op['scope'], token].append((source, op['id']))
                if op['statement'] in selected[source]:
                    self.by_statement[source, op['statement']].append((source, op['id']))
            for d in behavior.definitions:
                self.definitions[source, d['id']] = d
            relations = graph.relation_index if graph.behavior_index is behavior else RelationIndex(graph, behavior)
            for op in behavior.operations:
                self.observation_fields[source, op['id']] = tuple(relations.operation_features[op['id']]['observation_fields'])
            for edge in relations.edges:
                if edge['kind'] == 'operation_observation_candidate':
                    continue
                before, after = (source, edge['from']), (source, edge['to'])
                self.incoming[after].append((before, edge))
                self.outgoing[before].append((after, edge))
                self.tracking_counts[edge['kind']] += 1
        self.aliases = callee_members(self)
        self.flow_components = self._flow_components()

    def _flow_components(self):
        """Weak data dependence for lifting a D seed to its connected operations.

        Sharing an unresolved global function spelling is excluded. Captured
        value dependencies remain may edges; this does not merge their objects.
        """
        parent = {}

        def find(key):
            parent.setdefault(key, key)
            while parent[key] != key:
                parent[key] = parent[parent[key]]
                key = parent[key]
            return key

        for after, edges in self.incoming.items():
            for before, edge in edges:
                if before[1] in self.reporting or after[1] in self.reporting:
                    continue
                if edge['kind'] == 'unresolved_binding_use' and edge['evidence']['port'] == 'callee':
                    continue
                if edge['kind'] == 'construction_input' and edge['evidence']['use'] == 'callable':
                    continue
                if edge['evidence'].get('port') == 'callee' and before in self.definitions:
                    declaration = self.definitions[before]
                    if declaration['value_range'] is None and declaration['value_kind'] != 'parameter':
                        continue
                a, b = find(before), find(after)
                if a != b:
                    parent[b] = a
        return {key: find(key) for key in self.operations}

    def consumer_state(self, key):
        """Follow result consumers to observations and their receiver branch.

        A second call on the consumer's receiver is a possible state event.
        Relative source order is retained with that uncertainty, not promoted
        to an observed effect. Separate function frames are not traversed.
        """
        source, _ = key
        root = self.operations[key]
        todo, seen, rows = [key], set(), set()
        while todo:
            current = todo.pop()
            if current in seen:
                continue
            seen.add(current)
            if current in self.operations:
                op = self.operations[current]
                if op['scope'] != root['scope']:
                    continue
                receiver = op['receiver']
                if receiver is not None:
                    value = receiver['value_identity']
                    binding = tuple(receiver['binding']) if receiver['binding'] is not None else None
                    token = ('value', value) if value is not None else ('cell', binding) if binding is not None else None
                    if token is not None:
                        for other in self.receiver_users[source, op['scope'], token]:
                            event = self.operations[other]
                            if other in {key, current} or event['kind'] not in {'call', 'member_write', 'subscript_write'}:
                                continue
                            position = 'before_root' if event['expression_range'][1] <= root['expression_range'][0] else 'after_root'
                            rows.add((current, other, position,
                                      'possible_receiver_effect', 'symbolic_value' if value is not None else 'lexical_cell'))
                if current != key and (op['observation'] is not None or op['kind'] == 'return'):
                    continue
            todo.extend(after for after, edge in self.outgoing[current]
                        if edge['kind'] != 'construction_input' or edge['evidence']['use'] != 'callable')
        return sorted(rows, key=repr)

    def definition_sources(self, key):
        """Follow definition input edges to calls, retaining cyclic frontiers."""
        if key in self.definition_producers:
            return self.definition_producers[key]
        todo, seen, producers, definitions = [key], set(), set(), set()
        while todo:
            current = todo.pop()
            if current in seen:
                continue
            seen.add(current)
            if current in self.operations:
                producers.add(current)
                continue
            if current in self.definitions:
                definitions.add(current)
            todo.extend(before for before, _ in self.incoming[current])
        result = producers, definitions
        self.definition_producers[key] = result
        return result

    def descriptor(self, key):
        if key in self.descriptors:
            return self.descriptors[key]
        source, _ = key
        graph, _ = self.sources[source]
        op = self.operations[key]
        name = op['name']
        if op['callee'] is not None:
            a, b = op['callee']['range']
            node = graph.root.descendant_for_byte_range(a, b)
            if node.type in {'scoped_identifier', 'generic_function', 'scoped_type_identifier'}:
                name = graph.text(node)
        result = op['kind'], name
        self.descriptors[key] = result
        return result

    def _syntax(self, source, span):
        key = source, tuple(span)
        if key not in self.references:
            term = self.terms[source].term(span)
            selectors, todo = [], [term]
            while todo:
                node = todo.pop()
                if node.kind in SUBSCRIPTS:
                    selectors.append(term_key(node, rename=True))
                todo.extend(child for _, child in node.children)
            self.references[key] = (digest(term_key(term, rename=True)),
                                    digest((term_template(term)[0], selectors)))
        return self.references[key]

    def port_number(self, source, port):
        term = self.terms[source].term(port['range'])
        value = literal_number(term)
        if value is not None:
            return value
        if term.kind == 'reference' and len(port['definition_versions']) == 1:
            _, definitions = self.definition_sources((source, port['definition_versions'][0]))
            values = {literal_number(self.terms[source].term(self.definitions[d]['value_range']))
                      for d in definitions if self.definitions[d]['value_range'] is not None
                      and self.definitions[d]['value_kind'] == 'literal'}
            if len(values) == 1:
                return values.pop()
        return None

    def construction(self, key):
        """Reach all explicit inputs, including arguments of producing calls.

        No text window is expanded. Traversal stops at external parameters or
        unresolved lexical cells, and cycles are represented by their endpoints.
        """
        todo, seen, definitions, producers = [key], set(), set(), set()
        while todo:
            current = todo.pop()
            if current in seen:
                continue
            seen.add(current)
            if current in self.definitions:
                definitions.add(current)
            if current in self.operations:
                producers.add(current)
            todo.extend(before for before, _ in self.incoming[current])
        return definitions, producers

    def _field_role(self, key):
        source, _ = key
        graph, _ = self.sources[source]
        op = self.operations[key]
        a, b = op['expression_range']
        node = graph.root.descendant_for_byte_range(a, b)
        while node.parent is not None and node.parent.end_byte <= graph.nodes[op['statement']]['end']:
            node = node.parent
            if node.type in {'pair', 'keyed_element', 'field_initializer', 'property_assignment'}:
                field = node.child_by_field_name('key') or node.child_by_field_name('field')
                if field is not None:
                    return graph.text(field)
        return None

    def feature(self, key):
        if key in self.features:
            return self.features[key]
        source, _ = key
        graph, behavior = self.sources[source]
        op = self.operations[key]
        inputs, outputs = [], []
        # Each edge keeps its actual input role. Sharing a reporting handle is
        # not a dependency on the value being tested.
        for before, edge in self.incoming[key]:
            if before[1] in self.reporting:
                continue
            producers, definitions = self.definition_sources(before)
            role = edge['evidence'].get('port', 'result')
            for producer in producers - {key}:
                if producer in self.aliases:
                    continue
                inputs.append((role, producer))
        todo = [(after, edge['evidence'].get('port', 'result')) for after, edge in self.outgoing[key]]
        seen = set()
        while todo:
            after, role = todo.pop()
            if (after, role) in seen:
                continue
            seen.add((after, role))
            if after in self.operations:
                if after not in self.aliases:
                    outputs.append((role, after))
                continue
            todo.extend((nxt, edge['evidence'].get('port', role)) for nxt, edge in self.outgoing[after])
        definitions, producers = self.construction(key)
        pp = ports(op)
        syntax = [(p['role'], *self._syntax(source, p['range'])) for p in pp]
        traces = []
        for dkey in sorted(definitions):
            d = self.definitions[dkey]
            span = d['value_range']
            if span is not None:
                traces.append((d['value_kind'], *self._syntax(source, span)))
        identities = []
        for port in pp:
            if behavior.suffix in REFERENCE_LANGUAGES and port['ast_type'] in FRESH['.py' if behavior.suffix == '.py' else '.js']:
                identities.append({**port, 'identity_kind': 'fresh_allocation',
                                   'value_identity': (source, *port['range'])})
            else:
                identities.append(port)
        identity = [(a['role'], b['role'], identity_relation(a, b))
                    for i, a in enumerate(identities) for b in identities[i+1:]]
        numbers = [(p['role'], self.port_number(source, p)) for p in pp]
        value_relations = [(a, b, 'equal' if x == y else 'less' if x < y else 'greater')
                           for i, (a, x) in enumerate(numbers) for b, y in numbers[i+1:]
                           if x is not None and y is not None]
        guards = [(g['polarity'], *self._syntax(source, g['range'])) for g in op['guards']]
        state_evidence = self.consumer_state(key)
        state = sorted({(self.descriptor(c), self.descriptor(o), *rest)
                        for c, o, *rest in state_evidence}, key=repr)
        connections = []
        for direction, edges in [('inputs', inputs), ('outputs', outputs)]:
            for role, other in edges:
                start, end = self.operations[other]['expression_range']
                position = ('before' if end <= op['expression_range'][0] else
                            'after' if start >= op['expression_range'][1] else 'nested')
                connections.append((direction, role, self.descriptor(other), position))
        exact = ([(r, e) for r, e, _ in syntax], sorted((k, e) for k, e, _ in traces),
                 identity, value_relations, state, [(p, e) for p, e, _ in guards], sorted(set(connections), key=repr))
        template = ([(r, t) for r, _, t in syntax], sorted((k, t) for k, _, t in traces),
                    identity, value_relations, state, [(p, t) for p, _, t in guards], sorted(set(connections), key=repr))
        field = self._field_role(key)
        result = {'key': key, 'interface': self.descriptor(key), 'inputs': sorted(set(inputs)),
                  'outputs': sorted(set(outputs)), 'field': field,
                  'exact': digest(exact), 'template': digest(template),
                  'identity_relations': identity, 'value_relations': value_relations,
                  'observation': op['observation'] is not None,
                  'consumer_state': state_evidence,
                  'definitions': sorted(definitions), 'producers': sorted(producers)}
        self.features[key] = result
        return result

    def view_features(self, view):
        selected = {key for n in view['nodes'] for key in self.by_statement[view['source'], n]}
        anchors = {self.aliases.get(key, key) for key in view['anchors']}
        components = {self.flow_components[key] for key in anchors}
        records = []
        for key in sorted(selected - self.aliases.keys()):
            base = self.feature(key)
            keys, suppliers, receiver = set(), set(), set()
            observed_keys = set()
            carrier = base['interface'], base['field']
            observed_carrier = carrier, self.observation_fields[key]
            for direction in ['inputs', 'outputs']:
                for role, other in base[direction]:
                    if other not in selected:
                        continue
                    label = self.descriptor(other)
                    keys.add((carrier, direction, role, label))
                    observed_label = label, self.observation_fields[other]
                    observed_keys.add((observed_carrier, direction, role, observed_label))
                    if direction == 'inputs' and role != 'callee':
                        suppliers.add(label)
                    if direction == 'inputs' and role == 'receiver':
                        receiver.add(label)
            if base['field'] is not None:
                keys.add((carrier, 'field', base['field']))
                observed_keys.add((observed_carrier, 'field', base['field']))
            # The graph endpoints remain separate even if these signatures agree.
            records.append({**base, 'view': view['id'], 'anchor': key in anchors,
                            'flow_anchor': self.flow_components[key] in components,
                            'roles': keys, 'suppliers': suppliers, 'receiver': receiver})
            records[-1]['observed_roles'] = observed_keys
        return records


def admission_witnesses(record, mode):
    if mode == 'subject' and record['observation']:
        return set()
    witnesses = record['observed_roles'] if mode in {'observed', 'subject'} else record['roles']
    if mode == 'two_edge':
        witnesses = set(combinations(sorted(witnesses, key=repr), 2))
    if mode == 'receiver' and record['receiver']:
        witnesses = {(w, tuple(sorted(record['receiver'], key=repr))) for w in witnesses}
    return witnesses


def operation_endpoints(operations, start, end):
    """Prefer exact/contained operations before the smallest enclosing one."""
    candidates = [(op['id'], op['expression_range']) for op in operations]
    exact = {key for key, span in candidates if span == [start, end]}
    contained = {key for key, (a, b) in candidates if start <= a and b <= end}
    enclosing = [(b - a, key) for key, (a, b) in candidates if a <= start and end <= b]
    chosen = exact or contained or ({min(enclosing)[1]} if enclosing else set())
    return chosen


def endpoint_operations(index, source, start, end):
    operations = [op for key, op in index.operations.items() if key[0] == source]
    return {index.aliases.get((source, operation), (source, operation))
            for operation in operation_endpoints(operations, start, end)}


def admission_seed(record, mode):
    return record['flow_anchor'] if mode in {'connected', 'observed', 'subject'} else record['anchor']


def admission_groups(records, mode):
    """Inverted witness keys avoid whole-slice Cartesian products.

    `edge` requires a common port-linked neighbor; `receiver` additionally
    requires compatible known receiver producers. `supply` connects a consumer
    to an existing producing interface rather than requiring equal root names.
    """
    buckets, groups, ids = defaultdict(set), [], {}
    for record in records:
        witnesses = admission_witnesses(record, mode)
        if mode == 'shape':
            signature = record['template']
        else:
            signature = record['exact']
        identity = record['interface'], signature, tuple(sorted(witnesses, key=repr))
        if identity not in ids:
            ids[identity] = len(groups)
            groups.append({'members': [], 'anchors': [], 'original_keys': [],
                           'signature': signature, 'exact_signatures': set(),
                           'interface': record['interface']})
        g = ids[identity]
        groups[g]['members'].append((record['view'], record['key'][1]))
        groups[g]['original_keys'].append(record['key'])
        groups[g]['exact_signatures'].add(record['exact'])
        if admission_seed(record, mode):
            groups[g]['anchors'].append((record['view'], record['key'][1]))
        for witness in witnesses:
            buckets[witness].add(g)
    domains = [{'groups': sorted(gs), 'anchor_groups': [g for g in sorted(gs) if groups[g]['anchors']]}
               for gs in buckets.values() if len(gs) > 1]
    domains = [d for d in domains if d['anchor_groups']]
    return groups, domains
