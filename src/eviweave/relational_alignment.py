"""Occurrence/port correspondence and conditional local relation differences.

Profiles share comparison work, not runtime identity. Every occurrence keeps
its source and endpoints. Unknown relations are not negative facts.
"""
from collections import defaultdict
import hashlib
import itertools
import json

from .alignment import TermIndex, anti_unify, term_key


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()


def ports(operation):
    return operation['arguments'] + ([operation['receiver']] if operation['receiver'] is not None else [])


def identity_relation(left, right):
    a, b = left['value_identity'], right['value_identity']
    if a is None or b is None:
        return 'unknown'
    if a == b:
        return 'same_symbolic_value'
    if left['identity_kind'] == right['identity_kind'] == 'fresh_allocation':
        return 'distinct_allocations'
    return 'unknown'


def view_pair_masks(groups, domains):
    """Project factored operation domains to distinct directed view pairs."""
    masks = [sum(1 << v for v in {p[0] for p in g['members']}) for g in groups]
    result = defaultdict(int)
    comparisons = 0
    for domain in domains:
        family = domain['groups']
        suffix = [0] * (len(family) + 1)
        for i in range(len(family) - 1, -1, -1):
            suffix[i] = suffix[i + 1] | masks[family[i]]
        prefix = 0
        for i, group in enumerate(family):
            others = prefix | suffix[i + 1]
            for view in {row[0] for row in groups[group]['anchors']}:
                result[view] |= others & ~(1 << view)
            if groups[group]['anchors']:
                comparisons += len(family) - 1
            prefix |= masks[group]
    return result, comparisons


class RelationalAlignmentIndex:
    def __init__(self, sources, selected):
        """sources: id -> (SourceGraph, BehaviorIndex); selected: id -> node IDs."""
        self.sources = sources
        self.terms = {source: TermIndex(graph) for source, (graph, _) in sources.items()}
        self.definitions = {source: {d['id']: d for d in behavior.definitions}
                            for source, (_, behavior) in sources.items()}
        self.operations, self.by_name = {}, defaultdict(list)
        self.by_statement = defaultdict(list)
        self.constructions = {}
        self.value_users, self.value_observers = defaultdict(list), defaultdict(list)
        self.profiles, self.syntax, self.references = {}, {}, {}
        self.producers = defaultdict(set)
        self.components = {}
        for source, (_, behavior) in sources.items():
            for op in behavior.operations:
                for definition in op['result']['definitions']:
                    self.producers[source, definition].add(op['id'])
                if op['statement'] not in selected[source]:
                    continue
                key = source, op['id']
                self.operations[key] = op
                self.by_statement[source, op['statement']].append(key)
                self.by_name[op['kind'], op['name']].append(key)
                values = {p['value_identity'] for p in ports(op) if p['value_identity'] is not None}
                values.update(read['value_identity'] for p in ports(op) for read in p['reads']
                              if read['value_identity'] is not None)
                for value in values:
                    self.value_users[source, op['scope'], value].append(key)
                    if op['observation'] is not None:
                        self.value_observers[source, op['scope'], value].append(key)
        for group in self.by_name.values():
            group.sort()

    def syntax_key(self, source, span):
        key = source, tuple(span)
        if key not in self.syntax:
            term = self.terms[source].term(span)
            self.syntax[key] = digest(term_key(term, rename=True))
            pending, refs = [term], []
            while pending:
                item = pending.pop()
                if item.kind == 'reference':
                    refs.append(item.value)
                pending.extend(child for _, child in reversed(item.children))
            self.references[key] = refs
        return self.syntax[key]

    def construction(self, source, port):
        """Keep all reaching alternatives and reference chains without unrolling calls."""
        cache_key = source, tuple(port['range'])
        if cache_key in self.constructions:
            return self.constructions[cache_key]
        definitions = self.definitions[source]
        pending = list(port['definition_versions'])
        pending.extend(d for read in port['reads'] for d in read['definition_versions'])
        seen, rows, locations = set(), [], []
        while pending:
            identity = pending.pop()
            if identity in seen:
                continue
            seen.add(identity)
            definition = definitions[identity]
            span = definition['value_range']
            syntax = None if span is None else self.syntax_key(source, span)
            rows.append((definition['value_kind'], syntax, tuple(definition['unknowns'])))
            locations.append({'definition': identity, 'range': definition['range'], 'value_range': span})
            pending.extend(definition['source_versions'])
        result = sorted(rows, key=repr), sorted(locations, key=lambda row: row['definition'])
        self.constructions[cache_key] = result
        return result

    def profile(self, key, *, nodes=None, reporting_values=()):
        if nodes is None and not reporting_values and key in self.profiles:
            return self.profiles[key]
        source, _ = key
        graph, behavior = self.sources[source]
        op = self.operations[key]
        inputs, constructions, endpoints, reference_spans = [], [], [], []
        pp = ports(op)
        for port in pp:
            inputs.append((port['role'], self.syntax_key(source, port['range'])))
            reference_spans.append(('input:' + port['role'], port['range']))
            constructor, locations = self.construction(source, port)
            constructions.append((port['role'], constructor))
            endpoints.append({'role': port['role'], 'range': port['range'], 'definitions': locations,
                              'value_identity': port['value_identity'], 'identity_kind': port['identity_kind'],
                              'unknowns': port['unknowns']})
        identity = [(a['role'], b['role'], identity_relation(a, b)) for a, b in itertools.combinations(pp, 2)]
        guards = [(g['polarity'], self.syntax_key(source, g['range'])) for g in op['guards']]
        reference_spans.extend(('guard', g['range']) for g in op['guards'])
        phases = []
        for frame in op['frames']:
            kind = frame['kind']
            phases.append((kind, frame['branch'] if kind == 'try' else frame['mode'] if kind in {'cleanup', 'suspension'} else ''))
        values = {p['value_identity'] for p in pp if p['value_identity'] is not None}
        values.update(r['value_identity'] for p in pp for r in p['reads'] if r['value_identity'] is not None)
        values.update(self.definitions[source][d]['value_identity'] for d in op['result']['definitions'])
        values.difference_update(reporting_values)
        neighbors, observers = set(), set()
        for value in values - {None}:
            neighbors.update(self.value_users[source, op['scope'], value])
            observers.update(self.value_observers[source, op['scope'], value])
        order, observations, neighbor_endpoints, related_operations, state = [], [], [], [], []
        for other_key in sorted(neighbors - {key}, key=lambda k: (self.operations[k]['expression_range'], self.operations[k]['kind'])):
            other = self.operations[other_key]
            if nodes is not None and other['statement'] not in nodes:
                continue
            if other['kind'] not in {'call', 'assert', 'return', 'yield', 'await',
                                     'member_write', 'subscript_write'}:
                continue
            relation = ('before' if other['expression_range'][1] <= op['expression_range'][0] else
                        'after' if op['expression_range'][1] <= other['expression_range'][0] else 'nested')
            item = (other['kind'], other['name'], relation)
            order.append(item)
            related_operations.append((item, [(p['role'], self.syntax_key(source, p['range']))
                                              for p in ports(other)],
                                       [(g['polarity'], self.syntax_key(source, g['range']))
                                        for g in other['guards']]))
            if other['kind'] in {'member_write', 'subscript_write'}:
                state.append(related_operations[-1])
            if other_key in observers:
                observations.append((item, self.syntax_key(source, other['expression_range']),
                                     tuple((g['polarity'], self.syntax_key(source, g['range'])) for g in other['guards'])))
                reference_spans.append(('observation', other['expression_range']))
            neighbor_endpoints.append({'operation': other['id'], 'range': other['expression_range'],
                                       'name': other['name'], 'relative_position': relation,
                                       'observation': other_key in observers, 'guards': other['guards']})
        effects = [(e['kind'], e['target'], e.get('field'), e['certainty'])
                   for e in behavior._effects_by_operation[op['id']]]
        # One alpha map across inputs, guards and observations prevents a guard
        # on a different value from becoming equal merely by local renaming.
        names, topology = {}, []
        for role, span in reference_spans:
            refs = self.references[source, tuple(span)]
            topology.append((role, [names.setdefault(ref, len(names)) for ref in refs]))
        parts = {'input_expression': inputs, 'input_construction': constructions, 'identity': identity,
                 'binding_topology': topology,
                 'condition': guards, 'phase': phases, 'order': sorted(order, key=repr),
                 'related_operation': sorted(related_operations, key=repr),
                 'state': sorted(state, key=repr),
                 'observation': sorted(observations, key=repr), 'effect': effects}
        signatures = {name: digest(value) for name, value in parts.items()}
        for name, value in parts.items():
            self.components[name, signatures[name]] = value
        # A short typed dependency-path baseline; endpoint identities are kept
        # in the full profile, not folded into this retrieval feature.
        footprint = sorted((port['role'], port['ast_type'],
                            tuple(sorted({row[0] for row in constructors})))
                           for port, (_, constructors) in zip(pp, constructions, strict=True))
        record = {'key': key, 'kind': op['kind'], 'name': op['name'], 'range': op['expression_range'],
                  'scope': op['scope'], 'statement': op['statement'], 'components': signatures,
                  'footprint': footprint, 'ports': endpoints, 'neighbors': neighbor_endpoints,
                  'guards': op['guards'], 'unknowns': sorted(set(op['unknowns']) | {
                      'relative_order_is_conditional_static_evidence', 'symbol_does_not_prove_dynamic_dispatch'})}
        if nodes is None and not reporting_values:
            self.profiles[key] = record
        return record

    def grouped_view_domains(self, views, *, reporting_values=()):
        """Compare each retained view, sharing signatures but not its context.

        Each view supplies its own statement nodes and anchor operation IDs.
        Members record (view ID, operation key); no neighboring operation from
        another view enters the profile's conditional relation differences.
        """
        groups, signatures, families = [], {}, defaultdict(list)
        for view in views:
            keys = {key for node in view['nodes'] for key in self.by_statement[view['source'],node]}
            for key in sorted(keys):
                profile = self.profile(key, nodes=view['nodes'], reporting_values=reporting_values)
                signature = profile['kind'], profile['name'], tuple(profile['components'].items())
                if signature not in signatures:
                    identity=len(groups);signatures[signature]=identity
                    groups.append({'kind':profile['kind'],'name':profile['name'],'components':profile['components'],
                                   'members':[],'anchors':[]})
                    families[profile['kind'],profile['name']].append(identity)
                group=groups[signatures[signature]]
                occurrence=[view['id'],key[1]]
                group['members'].append(occurrence)
                if key in view['anchors']:group['anchors'].append(occurrence)
        domains=[]
        for (kind,name),family in families.items():
            active=[i for i in family if groups[i]['anchors']]
            if not active:continue
            n=sum(len(groups[i]['members']) for i in family)
            a=sum(len(groups[i]['anchors']) for i in active)
            unchanged=sum(len(groups[i]['anchors'])*(len(groups[i]['members'])-1) for i in active)
            domains.append({'kind':kind,'name':name,'groups':family,'anchor_groups':active,
                            'occurrence_pairs':a*(n-1),'changed_occurrence_pairs':a*(n-1)-unchanged})
        return groups,domains

    def align(self, left, right):
        a, b = self.profile(left), self.profile(right)
        assert (a['kind'], a['name']) == (b['kind'], b['name']), 'Cross-operation alignment requires an interface correspondence'
        left_ports = {p['role']: p for p in a['ports']}
        right_ports = {p['role']: p for p in b['ports']}
        mapping = [{'role': role, 'left': left_ports[role], 'right': right_ports[role]}
                   for role in sorted(left_ports.keys() & right_ports.keys())]
        delta = [{'kind': name, 'left': a['components'][name], 'right': b['components'][name]}
                 for name in a['components'] if a['components'][name] != b['components'][name]]
        syntax = []
        for row in mapping:
            compared = anti_unify(self.terms[left[0]].term(row['left']['range']),
                                 self.terms[right[0]].term(row['right']['range']))
            syntax.extend({'port': row['role'], **hole} for hole in compared['holes'])
        return {'left': left, 'right': right, 'ports': mapping, 'delta': delta,
                'input_syntax_edits': syntax,
                'added_ports': sorted(right_ports.keys() - left_ports.keys()),
                'removed_ports': sorted(left_ports.keys() - right_ports.keys()),
                'footprint_equal': a['footprint'] == b['footprint'],
                'interpretation': 'role_correspondence_and_conditional_relation_differences'}

    def grouped_domains(self, anchors):
        """Factor complete same-operation domains, keeping every occurrence.

        Comparison-equivalent profiles share one comparison; their original
        positions, scopes and versions remain separate members.
        """
        groups, by_signature = [], {}
        families = defaultdict(list)
        for key in sorted(self.operations):
            profile = self.profile(key)
            signature = (profile['kind'], profile['name'], tuple(profile['components'].items()))
            if signature not in by_signature:
                group = len(groups)
                by_signature[signature] = group
                groups.append({'members': [], 'anchors': [], 'components': profile['components'],
                               'kind': profile['kind'], 'name': profile['name'], 'footprint': profile['footprint']})
                families[profile['kind'], profile['name']].append(group)
            row = groups[by_signature[signature]]
            row['members'].append(key)
            if key in anchors:
                row['anchors'].append(key)
        # A family describes the entire pair domain. Enumerating its Cartesian
        # product is unnecessary for counting or for requesting one alignment.
        domains = []
        for (kind, name), family in families.items():
            active = [i for i in family if groups[i]['anchors']]
            if not active:
                continue
            members = sum(len(groups[i]['members']) for i in family)
            anchors_count = sum(len(groups[i]['anchors']) for i in active)
            equal = sum(len(groups[i]['anchors']) * (len(groups[i]['members']) - 1) for i in active)
            all_pairs = anchors_count * (members - 1)
            domains.append({'kind': kind, 'name': name, 'groups': family, 'anchor_groups': active,
                            'target_resolution': 'named_role' if name is not None else 'unresolved_target',
                            'occurrence_pairs': all_pairs, 'changed_occurrence_pairs': all_pairs - equal,
                            'profile_pairs': sum(len(family) - 1 for _ in active)})
        return groups, domains

    def interface_pairs(self):
        """Observed local producer/consumer links, with explicit port endpoints.

        These are bridge evidence for cross-API composition, not an assertion
        that an arbitrary same-shaped value in another source is compatible.
        """
        result = []
        for key, op in self.operations.items():
            source = key[0]
            for port in ports(op):
                producers = set(port.get('producer_operations', ()))
                for identity in port['definition_versions']:
                    producers.update(self.producers[source, identity])
                for producer in sorted(producers):
                    if (source, producer) in self.operations:
                        result.append({'producer': [source, producer], 'consumer': list(key),
                                       'port': port['role'], 'range': port['range'], 'certainty': 'static_value_dependency'})
        return result
