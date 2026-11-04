"""Behavior on existing slice nodes, with source and execution escape hatches.

Facts are shared per source version. Unknown relationships remain candidates;
none of these annotations remove code, materials or prior dependency edges.
"""
import ast
from collections import defaultdict
import gzip
import json
from pathlib import Path
import posixpath

from .behavior import BehaviorIndex
from .relations import RelationIndex
from .evidence import STRINGS


def write_behavior_graph(path, graph):
    """Lossless storage of one shared version, including all uncertain facts."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(graph, ensure_ascii=False, separators=(',', ':')).encode()
    path.write_bytes(gzip.compress(raw, compresslevel=6, mtime=0))


def read_behavior_graph(path):
    return json.loads(gzip.decompress(Path(path).read_bytes()))


def indexes(graph):
    if graph.behavior_index is None:
        graph.behavior_index = BehaviorIndex(graph)
        graph.relation_index = RelationIndex(graph, graph.behavior_index)
    return graph.behavior_index, graph.relation_index


def source_behavior(graph, nodes):
    behavior, relations = indexes(graph)
    result = behavior.view(nodes)
    result['relations'] = relations.view((op['id'] for op in result['operations']),
                                         (d['id'] for d in result['definitions']))
    return result


def ports(operation):
    return operation['arguments'] + ([operation['receiver']] if operation['receiver'] is not None else [])


def connect_calls(view, program):
    """Bind F's call sites to expression ports and conditional callee effects.

    Nested/recursive calls keep their own bindings instead of flattening all
    call paths. A callable passed to a function remains a callable candidate.
    """
    for call in view['calls']:
        source, statement = call['site']
        target, scope = call['callee']
        caller, _ = indexes(program.load(source))
        callee, _ = indexes(program.load(target))
        operation = next((op for op in caller._by_statement[statement]
                          if 'call_range' in call and op['expression_range'] == call['call_range']
                          and op['kind'] == 'call'), None)
        body = callee.by_scope[scope]
        definition = program.load(target).scopes[scope]
        deferred = any(op['kind'] == 'yield' for op in body)
        asynchronous = program.load(target).text(definition['ast']).lstrip().startswith('async ')
        invocation = ('passed_callable_not_observed' if call['kind'] == 'callable_value'
                      else 'deferred_generator_body' if deferred else 'async_body_not_observed' if asynchronous
                      else 'framework_rule' if call['kind'] == 'framework_setup' else 'conditional_static_call')
        mapping = defaultdict(list)
        for argument in call['arguments']:
            parameter = argument['parameter']
            matching = ([] if operation is None else [p for p in operation['arguments']
                        if argument['range'][0] <= p['range'][0] and p['range'][1] <= argument['range'][1]])
            argument['ports'] = [p['role'] for p in matching]
            argument['definition'] = (None if parameter is None else
                                      f'{callee.source}:parameter:{scope}:{parameter}')
            if parameter is not None:
                mapping[parameter].extend(argument['ports'])
        if call.get('bound_receiver') is not None and operation is not None:
            mapping[call['bound_receiver']].append('receiver')
        effects = []
        by_id = {op['id']: op for op in body}
        for number, effect in callee.effects_by_scope[scope]:
            op = by_id[effect['operation']]
            port = next((p for p in ports(op) if p['role'] == effect['target']), None)
            bindings = [] if port is None else [r['binding'] for r in port['reads']]
            if port is not None and port['binding'] is not None:
                bindings.append(port['binding'])
            actual = sorted({role for owner, name in bindings if owner == scope for role in mapping[name]})
            effects.append({'effect': number, 'caller_ports': actual,
                            'binding': 'parameter_dependency' if actual else 'callee_context_or_unresolved'})
        call['behavior'] = {
            'operation': None if operation is None else operation['id'],
            'result': None if operation is None else operation['result']['id'],
            'invocation': invocation,
            'return_operations': [op['id'] for op in body if op['kind'] == 'return'],
            'effect_bindings': effects,
            'activation': {'site': call['site'], 'scope': call['callee'],
                           'identity': 'symbolic_call_site_not_dynamic_invocation'},
        }


def execution_context(trajectory, execution):
    """One IO inventory per execution; retain all events and all byte sources."""
    inputs, outputs = set(), set()
    events = trajectory.by_execution[execution]
    for event in events:
        for material, kind in trajectory.before[event]:
            if material in trajectory.materials and kind in {'reads', 'maps', 'uses_code', 'bytecode_equivalent'}:
                inputs.add(material)
        for material, kind in trajectory.after[event]:
            if material in trajectory.materials and kind == 'produces':
                outputs.add(material)
    return {'execution': execution, 'cwd': trajectory.events[execution]['cwd'],
            'inputs': sorted(inputs), 'outputs': sorted(outputs), 'events': list(events),
            'interpretation': 'observed_IO; operation-to-material links and process dependencies may be approximate'}


def material_links(view, program, context, materials):
    """Index literal paths against actual IO without an operation×input join.

    A literal path is a retrieval candidate, not proof of which call performed
    a read. Dynamic/unresolved paths retain the execution's entire IO inventory.
    """
    by_path = defaultdict(list)
    for material in sorted(set(context['inputs']) | set(context['outputs'])):
        info = materials[material]
        if info['kind'] == 'file':
            by_path[info['path']].append(material)
    links = []
    for file in view['files']:
        graph = program.load(file['material'])
        behavior, _ = indexes(graph)
        for op in behavior.view(file['nodes'] + file['context_nodes'])['operations']:
            for port in ports(op):
                start, end = port['range']
                node = graph.root.descendant_for_byte_range(start, end - 1)
                todo = [node]
                while todo:
                    item = todo.pop()
                    if item.type not in STRINGS:
                        todo.extend(reversed(item.named_children))
                        continue
                    text = graph.text(item)
                    if text.startswith('`') and text.endswith('`') and '${' not in text:
                        value = text[1:-1]
                    else:
                        try:
                            value = ast.literal_eval(text)
                        except (ValueError, SyntaxError):
                            continue  # The full expression and IO inventory remain available.
                    if not isinstance(value, str) or '\0' in value:
                        continue
                    path = posixpath.normpath(posixpath.join(context['cwd'], value))
                    if path in by_path:
                        links.append({'material': file['material'], 'operation': op['id'], 'port': port['role'],
                                      'range': [item.start_byte, item.end_byte],
                                      'candidates': by_path[path], 'certainty': 'literal_path_candidate'})
    return links


def select_exported_behavior(facts, nodes):
    """Read the same per-node view from the shared, serialized source facts."""
    selected = set(nodes)
    operations = [op for op in facts['operations'] if op['statement'] in selected]
    ids = {op['id'] for op in operations}
    definitions = [d for d in facts['definitions'] if d['statement'] in selected]
    used = {d for op in operations for p in ports(op) + ([op['callee']] if op['callee'] is not None else [])
            for read in [p, *p['reads']] for d in read['definition_versions']}
    definitions.extend(d for d in facts['definitions'] if d['id'] in used and d['statement'] not in selected)
    relation_ids = ids | {d['id'] for d in definitions}
    scopes = {op['scope'] for op in operations} | {d['binding'][0] for d in definitions}
    by_scope = {s['id']: s for s in facts['scopes']}
    for scope in list(scopes):
        parent = by_scope[scope]['parent']
        while parent is not None:
            scopes.add(parent)
            parent = by_scope[parent]['parent']
    return {**facts, 'operations': operations, 'definitions': definitions,
            'scopes': [s for s in facts['scopes'] if s['id'] in scopes],
            'order': [e for e in facts['order'] if e['before'] in ids and e['after'] in ids],
            'cfg': [e for e in facts['cfg'] if e['before'] in selected and e['after'] in selected],
            'effects': [e for e in facts['effects'] if e['operation'] in ids],
            'cells': [c for c in facts['cells'] if any(u['operation'] in ids for u in c['uses'])
                      or any(d['id'] in c['definitions'] for d in definitions)],
            'relations': {**facts['relations'],
                          'edges': [e for e in facts['relations']['edges']
                                    if e['from'] in relation_ids or e['to'] in relation_ids],
                          'operation_features': {key: value for key, value in facts['relations']['operation_features'].items()
                                                 if key in ids}}}
