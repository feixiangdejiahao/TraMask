"""Syntax support for Step D; no ownership gate, slicing or model calls.

The source binder recognizes imports, explicit types and direct constructions.
Unknown bindings stay eligible. Helper edges are file-local syntax references,
not execution or data-flow claims.
"""
from collections import defaultdict
from bisect import bisect_right
from functools import lru_cache
import re

from .anchors import FUNCTIONS, _parser, _call_name, js_test_registration

CALLS = {'call', 'call_expression', 'new_expression'}
MEMBERS = {'attribute', 'selector_expression', 'field_expression', 'member_expression'}
ANONYMOUS = {'lambda', 'lambda_expression', 'arrow_function', 'function_expression', 'func_literal', 'closure_expression'}


def merge_ranges(ranges):
    merged = []
    for start, end in sorted(set(map(tuple, ranges))):
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(end, merged[-1][1])
        else:
            merged.append([start, end])
    return merged


def covered(start, end, ranges):
    return any(a <= start and end <= b for a, b in ranges)


def outer_ranges(ranges):
    outer = []
    for a, b in sorted(set(ranges), key=lambda span: (span[0], -span[1])):
        if not outer or a >= outer[-1][1]:
            outer.append((a, b))
    return outer


@lru_cache(maxsize=4096)
def source_index(suffix, raw):
    root = _parser(suffix).parse(raw).root_node
    if root.has_error:
        return {'status': 'source_parse_error', 'points': {}, 'definitions': [], 'calls': [], 'episodes': [], 'tables': []}

    def text(node):
        return raw[node.start_byte:node.end_byte].decode() if node is not None else ''

    imports, definitions, call_nodes, member_nodes, registrations = {}, [], [], [], []
    local_types = set()
    table_nodes, loop_nodes = [], []

    def import_node(node):
        if node.type == 'import_statement' and suffix == '.py':
            for child in node.named_children:
                if child.type == 'aliased_import':
                    imports[text(child.child_by_field_name('alias'))] = ('module', text(child.child_by_field_name('name')))
                elif child.type == 'dotted_name':
                    name = text(child).split('.')[0]
                    imports[name] = ('module', name)
        elif node.type == 'import_from_statement':
            module = text(node.child_by_field_name('module_name'))
            for index, child in enumerate(node.children):
                if node.field_name_for_child(index) == 'name':
                    target = child.child_by_field_name('name') if child.type == 'aliased_import' else child
                    alias = child.child_by_field_name('alias') if child.type == 'aliased_import' else child
                    imports[text(alias)] = ('symbol', module, text(target))
        elif node.type == 'import_spec':
            path = text(node.child_by_field_name('path')).strip('"`')
            alias = text(node.child_by_field_name('name')) or path.rsplit('/', 1)[-1]
            if alias not in {'.', '_'}:
                imports[alias] = ('module', path)
        elif node.type == 'import_statement' and suffix != '.py':
            module = text(node.child_by_field_name('source')).strip('"\'')
            pending = list(node.named_children)
            while pending:
                child = pending.pop()
                if child.type == 'namespace_import':
                    imports[text(child.named_children[-1])] = ('module', module)
                elif child.type == 'import_specifier':
                    name = text(child.child_by_field_name('name'))
                    alias = text(child.child_by_field_name('alias')) or name
                    imports[alias] = ('symbol', module, name)
                elif child.type == 'import_clause':
                    for item in child.named_children:
                        if item.type == 'identifier':
                            imports[text(item)] = ('symbol', module, text(item))
                    pending.extend(child.named_children)
                else:
                    pending.extend(child.named_children)
        elif node.type == 'use_declaration':
            value = text(node).removeprefix('use ').rstrip(';').strip()
            if re.fullmatch(r'[\w:]+(?:\s+as\s+\w+)?', value):
                path, _, alias = value.partition(' as ')
                parts = path.split('::')
                imports[alias or parts[-1]] = ('symbol', '::'.join(parts[:-1]), parts[-1])

    todo = [root]
    while todo:
        node = todo.pop()
        import_node(node)
        if node.type in {'class_definition', 'class_declaration', 'type_spec', 'struct_item', 'enum_item'}:
            name = node.child_by_field_name('name')
            if name is not None:
                local_types.add(text(name))
        todo.extend(reversed(node.named_children))

    def type_identity(annotation):
        value = annotation.strip().lstrip(':').strip().lstrip('&*').strip()
        if not re.fullmatch(r'[\w.$:]+', value):
            return None
        parts = re.split(r'\.|::', value)
        imported = imports.get(parts[-1])
        name = imported[-1] if imported and imported[0] == 'symbol' else parts[-1]
        return ('type', name)

    def add_binding(scope, name, position, identity):
        scope['bindings'].setdefault(name, []).append((position, identity))

    def resolve(name, scope, position):
        while scope is not None:
            candidates = [value for offset, value in scope['bindings'].get(name, []) if offset < position]
            if candidates:
                return candidates[-1]
            scope = scope['parent']
        imported = imports.get(name)
        if imported:
            if imported[0] == 'module':
                return ('module', imported[1].split('.')[0].split('/')[0])
            return ('symbol', imported[1], imported[2])
        return None

    def infer(value, scope, position):
        value = value.strip()
        if re.fullmatch(r'[A-Za-z_$][\w$]*', value):
            return resolve(value, scope, position)
        match = re.match(r'(?:new\s+)?([\w.$:]+)\s*\(', value)
        if match:
            chain = re.split(r'\.|::', match[1])
            if chain[-1] in {'new', 'default'} and len(chain) > 1:
                name = chain[-2]
            else:
                name = chain[-1]
            imported = imports.get(name)
            if imported and imported[0] == 'symbol':
                name = imported[2]
            if value.startswith('new ') or name in local_types:
                return ('type', name)
        match = re.match(r'&?([A-Za-z_]\w*)\s*\{', value)
        if match:
            return ('type', match[1])
        if suffix == '.py':
            if value.startswith('['):
                return ('type', 'list')
            if value.startswith('{'):
                return ('type', 'dict')
            if value.startswith(('"', "'")):
                return ('type', 'str')
        return None

    module_scope = {'parent': None, 'bindings': {}, 'start': 0, 'end': len(raw), 'definition': None}

    def visit(node, scope, owner=None, branch=False):
        if node.type in {'class_definition', 'class_declaration', 'impl_item'}:
            owner_node = node.child_by_field_name('name') or node.child_by_field_name('type')
            owner = text(owner_node).lstrip('&*')
        named = node.type in FUNCTIONS
        if node.type == 'method_declaration':
            receiver = node.child_by_field_name('receiver')
            annotation = receiver.named_children[0].child_by_field_name('type')
            identity = type_identity(text(annotation))
            owner = identity[1] if identity else None
        if named or node.type in ANONYMOUS:
            scope = {'parent': scope, 'bindings': {}, 'start': node.start_byte,
                     'end': node.end_byte, 'definition': None}
            if owner:
                for receiver in ('self', 'this'):
                    add_binding(scope, receiver, node.start_byte - 1, ('type', owner))
            if named:
                name = text(node.child_by_field_name('name'))
                definition = {'name': name, 'owner': owner, 'start': node.start_byte,
                              'end': node.end_byte, 'testing_parameter': False}
                scope['definition'] = len(definitions)
                definitions.append(definition)
            params = node.child_by_field_name('parameters')
            receiver = node.child_by_field_name('receiver')
            for parent in [part for part in (params, receiver) if part is not None]:
                for parameter in parent.named_children:
                    annotation = parameter.child_by_field_name('type')
                    binding = (parameter.child_by_field_name('name') or parameter.child_by_field_name('pattern'))
                    if binding is None and annotation is not None:
                        binding = next((n for n in parameter.named_children if n.type == 'identifier'), None)
                    if binding is not None and annotation is not None:
                        identity = type_identity(text(annotation))
                        add_binding(scope, text(binding), node.start_byte - 1, identity)
                        if named and identity == ('type', 'T') and any(
                                item[0] == 'module' and item[1] == 'testing' for item in imports.values()):
                            definitions[scope['definition']]['testing_parameter'] = True
            branch = False
        if node.type in {'if_statement', 'for_statement', 'while_statement', 'match_expression', 'switch_statement'}:
            branch = True
        if node.type in {'assignment', 'variable_declarator', 'short_var_declaration', 'let_declaration', 'var_spec'}:
            left = (node.child_by_field_name('left') or node.child_by_field_name('name')
                    or node.child_by_field_name('pattern'))
            right = node.child_by_field_name('right') or node.child_by_field_name('value')
            if left is not None and right is not None:
                name = text(left)
                if re.fullmatch(r'[A-Za-z_$][\w$]*', name):
                    add_binding(scope, name, node.start_byte, None if branch else infer(text(right), scope, node.start_byte))
        if node.type in CALLS:
            call_nodes.append((node, scope))
            if js_test_registration(raw, node) in {'test', 'it', 'specify'}:
                registrations.append((node.start_byte, node.end_byte))
        if node.type in MEMBERS:
            member_nodes.append((node, scope))
        if suffix == '.go' and node.type == 'composite_literal':
            table_nodes.append((node, scope))
        if suffix == '.go' and node.type == 'for_statement':
            loop_nodes.append((node, scope))
        return [(child,scope,owner,branch) for child in node.named_children]

    todo=[(root,module_scope,None,False)]
    while todo:
        node,scope,owner,branch=todo.pop()
        todo.extend(reversed(visit(node,scope,owner,branch)))
    by_name = defaultdict(list)
    for index, definition in enumerate(definitions):
        by_name[definition['name']].append(index)

    def identity_for_member(node, scope):
        obj = next((node.child_by_field_name(field) for field in ('object', 'operand', 'value')
                    if node.child_by_field_name(field) is not None), None)
        value = text(obj)
        if re.fullmatch(r'[A-Za-z_$][\w$]*', value):
            return resolve(value, scope, node.start_byte)
        parts = value.split('.')
        if parts[0] in imports and imports[parts[0]][0] == 'module':
            if len(parts) > 1 and parts[-1][:1].isupper():
                return ('type', parts[-1])
            return ('module', imports[parts[0]][1].split('.')[0].split('/')[0])
        return None

    points, calls, episodes = {}, [], list(registrations)
    for node, scope in member_nodes:
        points[node.start_byte, node.end_byte] = identity_for_member(node, scope)
    for node, scope in call_nodes:
        name = _call_name(raw, node)
        if name is None:
            continue
        function = node.child_by_field_name('function') or node.child_by_field_name('constructor')
        identity = identity_for_member(function, scope) if function.type in MEMBERS else None
        if function.type == 'identifier':
            binding = resolve(text(function), scope, node.start_byte)
            if binding and binding[0] == 'symbol':
                identity = ('module', binding[1].split('.')[0].split('/')[0])
        points[node.start_byte, node.end_byte] = identity
        options = by_name[name]
        if function.type == 'identifier':
            options = [i for i in options if not definitions[i]['owner']]
        elif identity and identity[0] == 'type':
            options = [i for i in options if definitions[i]['owner'] == identity[1]]
        else:
            options = []
        callee = options[0] if len(options) == 1 else None
        enclosing = scope
        while enclosing is not None and enclosing['definition'] is None:
            enclosing = enclosing['parent']
        caller = enclosing['definition'] if enclosing is not None else None
        calls.append({'name': name, 'start': node.start_byte, 'end': node.end_byte,
                      'identity': identity, 'caller': caller, 'callee': callee})
        if callee is not None and definitions[callee]['testing_parameter']:
            episodes.append((node.start_byte, node.end_byte))
        if suffix == '.go' and name == 'Run' and identity == ('type', 'T'):
            episodes.append((node.start_byte, node.end_byte))
    # Outer case calls own nested assertions/helper calls; nested ranges do not
    # independently remove the containing case's statements.
    episodes = outer_ranges(episodes)
    tables = []
    for node, scope in table_nodes:
        if scope['definition'] is None:
            continue
        definition = definitions[scope['definition']]
        if not (definition['testing_parameter'] or definition['name'].startswith(('Test', 'Example', 'Fuzz'))):
            continue
        type_node, body = node.child_by_field_name('type'), node.child_by_field_name('body')
        if type_node is None or type_node.type not in {'slice_type', 'array_type'} or body is None:
            continue
        rows = [(child.start_byte, child.end_byte) for child in body.named_children
                if child.type == 'literal_element' and child.named_children
                and child.named_children[0].type in {'literal_value', 'composite_literal'}]
        if len(rows) < 2:
            continue
        parent = node.parent
        while parent is not None and parent.type not in {'short_var_declaration', 'var_spec', 'assignment', 'block'}:
            parent = parent.parent
        if parent is None or parent.type == 'block':
            continue
        left = parent.child_by_field_name('left') or parent.child_by_field_name('name')
        name = text(left)
        if not re.fullmatch(r'[A-Za-z_]\w*', name):
            continue
        consumers = []
        for loop, loop_scope in loop_nodes:
            if loop_scope is not scope:
                continue
            clause = next((child for child in loop.named_children if child.type == 'range_clause'), None)
            if clause is not None and text(clause.child_by_field_name('right')) == name and any(
                    loop.start_byte <= a and b <= loop.end_byte for a, b in episodes):
                consumers.append((loop.start_byte, loop.end_byte))
        if consumers:
            tables.append({'rows': rows, 'consumers': consumers})
            episodes.extend(rows)
    episodes = outer_ranges(episodes)
    return {'status': 'indexed', 'points': points, 'definitions': definitions,
            'calls': calls, 'episodes': episodes, 'tables': tables}


def query_origins(issue, changes, final_sources, sources, indexes):
    expected = defaultdict(set)
    owners = set()
    for source in final_sources:
        path = source['path'].removeprefix('/app/')
        for definition in source['parsed']['declarations']:
            if definition['owner'] and any(definition['first_line'] <= line <= definition['last_line']
                                           for line in changes[path]):
                owners.add(definition['owner'])
        starts = [0]
        for line in source['raw'].splitlines(keepends=True):
            starts.append(starts[-1] + len(line))
        for call in indexes[source['id']]['calls']:
            if call['identity'] and bisect_right(starts, call['start']) in changes[path]:
                expected[call['name']].add(tuple(call['identity']))
    for source in sources:
        for declaration in source['parsed']['declarations']:
            if declaration['owner'] in owners:
                expected[declaration['name']].add(('type', declaration['owner']))
    for owner, member in re.findall(r'\b([A-Z][A-Za-z_0-9]*)\.([A-Za-z_]\w*)', issue):
        expected[member].add(('type', owner))
    return dict(expected)


def origin_conflict(identity, expected):
    """Only distinguish fully known origins of the same syntactic kind."""
    if identity is None or not expected:
        return False
    identity = tuple(identity)
    comparable = [tuple(item) for item in expected if item[0] == identity[0]]
    return len(comparable) == len(expected) and all(item != identity for item in comparable)


def helper_anchors(index, names, origins=None):
    reached = {call['caller'] for call in index['calls'] if call['name'] in names and call['caller'] is not None
               and (origins is None or not origin_conflict(call['identity'], origins.get(call['name'], set())))}
    changed = True
    while changed:
        changed = False
        for call in index['calls']:
            if call['callee'] in reached and call['caller'] is not None and call['caller'] not in reached:
                reached.add(call['caller'])
                changed = True
    return [(call['start'], call['end']) for call in index['calls'] if call['callee'] in reached]


def case_ranges(start, end, anchors, episodes, tables=()):
    anchors = list(anchors)
    for table in tables:
        if any(c <= a and b <= d for a, b in anchors for c, d in table['consumers']):
            anchors.extend(table['rows'])
        if any(c <= a and b <= d for a, b in anchors for c, d in table['rows']):
            anchors.extend((a, b) for a, b in episodes
                           if any(c <= a and b <= d for c, d in table['consumers']))
    episodes = [(a, b) for a, b in episodes if start <= a and b <= end]
    if not episodes:
        return [[start, end]], 0
    kept, position = [], start
    for a, b in episodes:
        if position < a:
            kept.append((position, a))
        if any(a <= c and d <= b for c, d in anchors):
            kept.append((a, b))
        position = b
    if position < end:
        kept.append((position, end))
    return merge_ranges(kept), len(episodes)


def template_key(path, source_sha256, ranges):
    """Share syntax preparation only; every execution origin stays attached."""
    return path.removeprefix('/app/'), source_sha256, tuple(map(tuple, ranges))
