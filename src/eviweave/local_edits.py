"""Two bounded, syntax-grounded JS/TS edit rules for controlled-entry pilots.

The rules enumerate deletions observed at corresponding call roles and closed
primitive object literals. They preserve the existing observation expressions;
that does not establish oracle applicability or behavioral equivalence.
"""
from collections import defaultdict
from itertools import combinations
import hashlib

from .evidence import CALLS, FUNCTION_NODES, STRINGS


PRIMITIVES = {'number', 'true', 'false', 'null', 'string'}
COMMENTS = {'comment', 'line_comment', 'block_comment'}


def apply_edits(raw, edits):
    ordered = sorted(edits, key=lambda e: tuple(e['range']))
    previous = 0
    chunks = []
    for edit in ordered:
        a, b = edit['range']
        if a < previous:
            raise ValueError('Overlapping edit intervals')
        if raw[a:b] != edit['before'].encode():
            raise ValueError('Edit bytes do not correspond to the source version')
        chunks.extend((raw[previous:a], edit['replacement'].encode()))
        previous = b
    chunks.append(raw[previous:])
    return b''.join(chunks)


def _fixed_fields(graph, node):
    if node.type != 'object':
        return None
    fields = [child for child in node.named_children if child.type not in COMMENTS]
    result = {}
    for field in fields:
        if field.type != 'pair':
            return None
        key = field.child_by_field_name('key')
        if key.type not in {'property_identifier', 'identifier', 'string', 'number'}:
            return None
        name = graph.text(key).strip('"\'')
        if name in result:
            return None
        result[name] = field
    return result


def _primitive(node):
    if node.type in PRIMITIVES:
        return True
    return (node.type == 'unary_expression' and len(node.named_children) == 1 and
            node.named_children[0].type == 'number' and node.children[0].type in {'-', '+'})


def _tokens(graph, node):
    pending, result = [node], []
    while pending:
        current = pending.pop()
        if current.type in COMMENTS:
            continue
        if current.type in STRINGS or not current.children:
            result.append(graph.text(current))
        else:
            pending.extend(reversed(current.children))
    return tuple(result)


def _deletions(graph, parent, removed):
    children = [child for child in parent.named_children if child.type not in COMMENTS]
    removed_ids = {node.id for node in removed}
    if len(removed_ids) == len(children):
        return [[parent.start_byte+1, parent.end_byte-1]]
    ranges, start = [], 0
    while start < len(children):
        if children[start].id not in removed_ids:
            start += 1
            continue
        end = start+1
        while end < len(children) and children[end].id in removed_ids:
            end += 1
        if end < len(children):
            ranges.append([children[start].start_byte, children[end].start_byte])
        else:
            ranges.append([children[start-1].end_byte, children[end-1].end_byte])
        start = end
    return ranges


class LocalEditIndex:
    def __init__(self, sources):
        self.sources = sources
        self.objects = defaultdict(list)
        self.pairs = defaultdict(list)
        self.scopes = {}
        self.operations = []
        self.observations = defaultdict(list)
        for source, (graph, behavior) in sources.items():
            self.operations.extend((source, op) for op in behavior.operations if op['kind'] == 'call')
            self.observations[source] = [op['expression_range'] for op in behavior.operations if op['observation'] is not None]
            owners = {node['ast'].id: node['scope'] for node in graph.nodes}
            pending = [(graph.root, 0)]
            while pending:
                node, scope = pending.pop()
                scope = owners.get(node.id, scope)
                self.scopes[source, node.id] = scope
                if node.type == 'object':
                    self.objects[source].append(node)
                if node.type == 'pair':
                    self.pairs[source].append(node)
                for child in reversed(node.named_children):
                    child_scope = graph.scope_nodes[node.id] if node.type in FUNCTION_NODES and child == node.child_by_field_name('body') else scope
                    pending.append((child, child_scope))

    def _edit(self, source, span, replacement=''):
        graph, _ = self.sources[source]
        return {'source': source, 'range': list(span), 'before': graph.raw[slice(*span)].decode(), 'replacement': replacement}

    def _preserves_observations(self, source, edits):
        return all(not (edit['range'][0] < b and a < edit['range'][1])
                   for edit in edits for a, b in self.observations[source])

    def _recipe(self, recipes, source, rule, edits, donor, details):
        if not self._preserves_observations(source, edits):
            return
        key = tuple((tuple(e['range']), e['replacement']) for e in edits)
        if key not in recipes:
            recipes[key] = {'rule': rule, 'edits': edits, 'donors': [], 'details': details,
                            'observations_preserved': True, 'oracle_applicability': 'requires_execution_and_contract_review'}
        recipes[key]['donors'].append(donor)

    def deletion_plans(self, source, span):
        graph, behavior = self.sources[source]
        target = next(op for op in behavior.operations if op['kind'] == 'call' and op['expression_range'] == list(span))
        recipes = {}
        for donor_source, donor in self.operations:
            if donor['name'] != target['name'] or len(donor['arguments']) >= len(target['arguments']):
                continue
            # Positional deletion keeps the remaining role positions stable.
            donor_roles = [p['role'] for p in donor['arguments']]
            target_roles = [p['role'] for p in target['arguments']]
            if donor_roles != target_roles[:len(donor_roles)]:
                continue
            call = graph.root.named_descendant_for_byte_range(span[0], span[1])
            arguments = call.child_by_field_name('arguments')
            children = [c for c in arguments.named_children if c.type not in COMMENTS]
            edits = [self._edit(source, r) for r in _deletions(graph, arguments, children[len(donor_roles):])]
            self._recipe(recipes, source, 'omit_arguments_observed_at_same_call_name', edits,
                         {'source': donor_source, 'range': donor['expression_range']},
                         {'operation': target['name'], 'omitted_roles': target_roles[len(donor_roles):]})
        receiver = target['receiver']
        identity = receiver['value_identity'] if receiver is not None else None
        setups = [op for op in behavior.operations if op['kind'] == 'call' and op['scope'] == target['scope']
                  and op['expression_range'][1] < span[0] and op['receiver'] is not None and identity is not None
                  and op['receiver']['value_identity'] == identity]
        for setup in setups:
            for argument in setup['arguments']:
                node = graph.root.named_descendant_for_byte_range(argument['range'][0], argument['range'][1])
                fields = _fixed_fields(graph, node)
                if fields is None:
                    continue
                for donor_source, donor in self.operations:
                    if donor['name'] != setup['name']:
                        continue
                    donor_graph, _ = self.sources[donor_source]
                    for donor_argument in donor['arguments']:
                        if donor_argument['role'] != argument['role']:
                            continue
                        donor_node = donor_graph.root.named_descendant_for_byte_range(donor_argument['range'][0], donor_argument['range'][1])
                        donor_fields = _fixed_fields(donor_graph, donor_node)
                        if donor_fields is None or not set(donor_fields) < set(fields):
                            continue
                        missing = set(fields)-set(donor_fields)
                        removed = [field for name, field in fields.items() if name in missing]
                        edits = [self._edit(source, r) for r in _deletions(graph, node, removed)]
                        self._recipe(recipes, source, 'omit_setup_fields_observed_at_same_call_role', edits,
                                     {'source': donor_source, 'range': donor_argument['range']},
                                     {'setup_operation': setup['name'], 'receiver_value_identity': identity,
                                      'target_operation': target['name'], 'removed_keys': sorted(missing),
                                      'retained_keys': sorted(donor_fields), 'argument_role': argument['role']})
        recipes = sorted(recipes.values(), key=lambda r: [(e['range'], e['replacement']) for e in r['edits']])
        candidates = {}
        for size in range(1, len(recipes)+1):
            for chosen in combinations(range(len(recipes)), size):
                edits = sorted([e for i in chosen for e in recipes[i]['edits']], key=lambda e: e['range'])
                if any(a['range'][1] > b['range'][0] for a, b in zip(edits, edits[1:])):
                    continue
                key = tuple((tuple(e['range']), e['replacement']) for e in edits)
                candidates.setdefault(key, {'edits': edits, 'recipe_choices': []})['recipe_choices'].append(list(chosen))
        return self._plans(source, span, target['scope'], recipes, sorted(candidates.values(), key=lambda c: [(e['range'], e['replacement']) for e in c['edits']]))

    def fresh_object_plans(self, source, span):
        graph, _ = self.sources[source]
        anchor = graph.root.named_descendant_for_byte_range(span[0], span[1])
        if anchor.type != 'pair':
            raise ValueError('The field-value entry must identify an object pair')
        scope = self.scopes[source, anchor.id]
        key = graph.text(anchor.child_by_field_name('key'))
        value = graph.text(anchor.child_by_field_name('value'))
        targets = [node.child_by_field_name('value') for node in self.pairs[source]
                   if self.scopes[source, node.id] == scope and graph.text(node.child_by_field_name('key')) == key
                   and graph.text(node.child_by_field_name('value')) == value]
        donors = {}
        for donor_source in sorted(self.sources):
            donor_graph, _ = self.sources[donor_source]
            for node in self.objects[donor_source]:
                fields = _fixed_fields(donor_graph, node)
                if not fields or not all(_primitive(pair.child_by_field_name('value')) for pair in fields.values()):
                    continue
                signature = _tokens(donor_graph, node)
                donor = {'source': donor_source, 'range': [node.start_byte, node.end_byte]}
                if signature not in donors:
                    donors[signature] = {'text': donor_graph.text(node), 'origins': []}
                donors[signature]['origins'].append(donor)
        recipes, candidates = [], []
        for donor in sorted(donors.values(), key=lambda d: (d['origins'][0]['source'], d['origins'][0]['range'])):
            edits = [self._edit(source, [node.start_byte, node.end_byte], donor['text']) for node in targets]
            if not self._preserves_observations(source, edits):
                continue
            index = len(recipes)
            recipes.append({'rule': 'replace_equal_field_values_with_separate_closed_object_literals',
                            'edits': edits, 'donors': donor['origins'],
                            'details': {'field_key': key, 'original_value': value, 'scope': scope,
                                        'separate_literal_occurrences': len(targets), 'introduced_free_bindings': []},
                            'observations_preserved': True, 'oracle_applicability': 'requires_execution_and_contract_review'})
            candidates.append({'edits': edits, 'recipe_choices': [[index]]})
        return self._plans(source, span, scope, recipes, candidates)

    def _plans(self, source, span, scope, recipes, candidates):
        graph, _ = self.sources[source]
        for position, candidate in enumerate(candidates, 1):
            candidate['id'] = f'C{position:04}'
            candidate['sha256'] = hashlib.sha256(apply_edits(graph.raw, candidate['edits'])).hexdigest()
        return {'source': source, 'entry_range': list(span), 'scope': scope, 'recipes': recipes,
                'candidates': candidates, 'total_candidates': len(candidates),
                'observation_ranges': self.observations[source], 'observations_preserved': True,
                'interpretation': 'controlled_entry_local_edits_not_minimality_or_complete_search'}
