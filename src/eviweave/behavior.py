"""Expression ports and conditional local behavior over one SourceGraph.

These are static events, not a trace. Identity tokens name values from one
activation; different tokens prove distinct objects only for fresh allocations.
The existing slicer's objects/callees remain may information. In particular,
passing a function does not establish that its body ran.
"""
from collections import defaultdict, deque
from bisect import bisect_left
from pathlib import PurePosixPath

from .anchors import _call_name
from .evidence import ASSIGN, CALLS, FUNCTION_NODES, IDENTS, LOOPS, MEMBERS, OBS, STRINGS


CONDITIONALS = {'if_statement', 'if_expression', 'elif_clause'}
FRESH = {'.py': {'list', 'dictionary', 'set', 'list_comprehension', 'dictionary_comprehension', 'set_comprehension'},
         '.js': {'array', 'object'}}
REFERENCE_LANGUAGES = {'.py', '.js', '.jsx', '.mjs', '.cjs', '.ts', '.tsx', '.mts', '.cts'}
SUBSCRIPTS = {'subscript', 'subscript_expression', 'index_expression'}
TRANSFERS = {'return_statement': 'return', 'return_expression': 'return',
             'yield': 'yield', 'yield_expression': 'yield',
             'await': 'await', 'await_expression': 'await'}


def _span(node):
    return [node.start_byte, node.end_byte]


def _unwrap(node):
    while node is not None and node.type in {'expression_list', 'parenthesized_expression'} and len(node.named_children) == 1:
        node = node.named_children[0]
    return node


def _member_base(node):
    return (node.child_by_field_name('object') or node.child_by_field_name('operand')
            or node.child_by_field_name('value'))


def _is_write_target(node):
    """A plain binding target is not a value read; mutation bases still are."""
    parent = node.parent
    while parent is not None and parent.type in {
        'expression_list', 'pattern_list', 'tuple_pattern', 'list_pattern',
        'array_pattern', 'object_pattern', 'parenthesized_expression',
    }:
        node, parent = parent, parent.parent
    if parent is None or parent.type not in ASSIGN:
        return False
    left = parent.child_by_field_name('left') or parent.child_by_field_name('name') or parent.child_by_field_name('pattern')
    operator = parent.child_by_field_name('operator')
    return node == left and (operator is None or operator.type in {'=', ':=', ':'})


class BehaviorIndex:
    """Build once per source version; views only select already indexed records."""

    def __init__(self, graph):
        self.graph = graph
        self.source = graph.source['id']
        self.suffix = PurePosixPath(graph.source['path']).suffix
        self.operations, self.definitions, self.order = [], [], []
        self.effects, self.cells = [], []
        self.issues = list(graph.issues)
        self._by_statement = defaultdict(list)
        self.by_scope = defaultdict(list)
        self.effects_by_scope = defaultdict(list)
        self._effects_by_operation = defaultdict(list)
        self._definitions_by_statement = defaultdict(list)
        self._view_definitions_by_statement = defaultdict(list)
        self._order_by_before = defaultdict(list)
        self._parameters_by_scope = defaultdict(dict)
        self._definition_by_id = {}
        self._operation_by_ast = {}
        self._identifier_reads = defaultdict(list)
        self._incoming = {}
        self._rebindable_cells = {binding for node in graph.nodes for binding in node['defs']
                                  if binding[0] != node['scope']}
        self.reachable = set()
        if graph.issues:
            return
        self._scan()
        self._index_definitions()
        self._reaching_definitions()
        self._bind_ports()
        self._index_order()
        self._index_effects()
        self._index_cells()
        for number, effect in enumerate(self.effects):
            effect['id'] = number
            self.effects_by_scope[effect['scope']].append((number, effect))
            self._effects_by_operation[effect['operation']].append(effect)
        for definition in self.definitions:
            self._view_definitions_by_statement[definition['statement']].append(definition)
        for edge in self.order:
            self._order_by_before[edge['before']].append(edge)

    def _id(self, kind, node):
        return f'{self.source}:{kind}:{node.start_byte}:{node.end_byte}'

    def _scan(self):
        graph = self.graph
        owners = {n['ast'].id: n['id'] for n in graph.nodes}
        # Decorators lie outside their function AST but belong to its header.
        for scope in graph.scopes:
            ast = scope['ast']
            if ast.parent is not None and ast.parent.type == 'decorated_definition':
                for decorator in ast.parent.named_children:
                    if decorator != ast:
                        owners[decorator.id] = scope['header']
        todo = [(graph.root, None, [], [])]
        self._assignments = []
        while todo:
            ast, statement, guards, frames = todo.pop()
            statement = owners.get(ast.id, statement)
            if ast.type in FUNCTION_NODES and ast.id not in graph.scope_nodes:
                self.issues.append({'kind': 'function_as_source_input', 'range': _span(ast),
                                    'reason': 'The function body is source material, not an execution frame.'})
                continue
            if statement is not None:
                if ast.type in ASSIGN:
                    self._assignments.append((ast, statement, frames))
                if ast.type in {'identifier', 'self', 'shorthand_property_identifier'}:
                    parent = ast.parent
                    if not (_is_write_target(ast) or
                            parent.type in MEMBERS and ast in [parent.child_by_field_name(f) for f in ('attribute', 'field', 'property')] or
                            parent.type == 'keyword_argument' and ast == parent.child_by_field_name('name')):
                        self._identifier_reads[statement].append(ast)
                if ast.type in CALLS | MEMBERS | SUBSCRIPTS | TRANSFERS.keys() | {'assert_statement'}:
                    self._operation(ast, statement, guards, frames)
            children = []
            false_guards = list(guards)
            condition = ast.child_by_field_name('condition')
            if ast.type in CONDITIONALS and condition is not None:
                false_guards.append({'statement': statement, 'range': _span(condition), 'polarity': False})
            for child in ast.named_children:
                child_guards, child_frames = list(guards), list(frames)
                if ast.type in FUNCTION_NODES and child == ast.child_by_field_name('body'):
                    child_guards = []
                    child_frames = [{'kind': 'function', 'scope': graph.scope_nodes[ast.id],
                                     'invocation': 'not_established'}]
                elif ast.type in CONDITIONALS:
                    if child == ast.child_by_field_name('consequence'):
                        child_guards.append({'statement': statement, 'range': _span(condition), 'polarity': True})
                    elif child in ast.children_by_field_name('alternative'):
                        child_guards = list(false_guards)
                        previous_condition = child.child_by_field_name('condition')
                        if child.type == 'elif_clause':
                            false_guards.append({'statement': owners[child.id], 'range': _span(previous_condition), 'polarity': False})
                if ast.type in LOOPS:
                    child_frames.append({'kind': 'loop', 'statement': statement,
                                         'range': _span(ast), 'iterations': 'unknown'})
                if ast.type == 'try_statement':
                    child_frames.append({'kind': 'try', 'statement': statement,
                                         'branch': child.type if child.type in {'except_clause', 'catch_clause', 'finally_clause'} else 'body'})
                if ast.type in {'with_statement', 'defer_statement'}:
                    child_frames.append({'kind': 'cleanup', 'statement': statement, 'mode': ast.type})
                if ast.type in {'await', 'await_expression', 'yield', 'yield_expression'}:
                    child_frames.append({'kind': 'suspension', 'range': _span(ast),
                                         'mode': TRANSFERS[ast.type], 'resumption': 'not_observed'})
                if ast.type in {'boolean_operator', 'binary_expression', 'conditional_expression', 'ternary_expression', 'optional_chain'}:
                    child_frames.append({'kind': 'expression_condition', 'range': _span(ast),
                                         'selection': 'not_resolved'})
                children.append((child, statement, child_guards, child_frames))
            todo.extend(reversed(children))

    def _port(self, ast, role, statement):
        value = _unwrap(ast)
        binding = (list(self.graph._binding(self.graph.nodes[statement]['scope'], self.graph.text(value)))
                   if value.type in IDENTS else None)
        return {'role': role, 'range': _span(ast), 'text': self.graph.text(ast),
                'ast_type': ast.type, 'binding': binding, 'definition_versions': [],
                'value_identity': None, 'identity_kind': 'unresolved', 'unknowns': []}

    def _operation(self, ast, statement, guards, frames):
        graph = self.graph
        kind = ('call' if ast.type in CALLS else 'assert' if ast.type == 'assert_statement'
                else 'annotation' if ast.type == 'attribute' and self.suffix == '.rs'
                else TRANSFERS[ast.type] if ast.type in TRANSFERS
                else 'subscript_read' if ast.type in SUBSCRIPTS else 'member_read')
        parent = ast.parent
        if kind in {'member_read', 'subscript_read'} and parent is not None and parent.type in ASSIGN:
            if ast in [parent.child_by_field_name('left'), parent.child_by_field_name('name')]:
                kind = kind.replace('_read', '_write')
        op = {'id': self._id(kind, ast), 'kind': kind, 'source': self.source,
              'statement': statement, 'scope': graph.nodes[statement]['scope'],
              'expression_range': _span(ast), 'ast_type': ast.type, 'name': None,
              'callee': None, 'arguments': [], 'receiver': None,
              'result': {'id': self._id('value', ast), 'definitions': []},
              'guards': guards, 'frames': frames, 'observation': None,
              'execution': 'static', 'targets': [], 'callback_values': [], 'unknowns': []}
        if kind == 'call':
            callee = ast.child_by_field_name('function') or ast.child_by_field_name('constructor') or ast.child_by_field_name('macro')
            op['name'] = graph.text(callee) if ast.type == 'macro_invocation' else _call_name(graph.raw, ast)
            if callee is not None:
                op['callee'] = self._port(callee, 'callee', statement)
                if callee.type in MEMBERS:
                    op['receiver'] = self._port(_member_base(callee), 'receiver', statement)
            args = ast.child_by_field_name('arguments')
            if args is not None:
                positional = 0
                for arg in args.named_children:
                    if arg.type == 'comment':
                        continue
                    if arg.type == 'keyword_argument':
                        role = 'keyword:' + graph.text(arg.child_by_field_name('name'))
                        value = arg.child_by_field_name('value')
                    else:
                        role, value = f'positional:{positional}', arg
                        positional += 1
                    port = self._port(value, role, statement)
                    if arg.type in {'list_splat', 'dictionary_splat', 'spread_element', 'variadic_argument'}:
                        port['unknowns'].append('expanded_argument_positions')
                    op['arguments'].append(port)
            if ast.type == 'macro_invocation':
                op['unknowns'].append('macro_expansion_and_argument_roles')
            if op['name'] and OBS.match(op['name']):
                op['observation'] = {'kind': 'name_candidate', 'inputs': [p['role'] for p in op['arguments']],
                                     'timing': 'at_call_after_operand_evaluation', 'reached': 'not_established'}
            op['unknowns'].append('callee_effects_and_exceptions')
            for call, target, relation in graph.call_sites[statement]:
                if call == ast:
                    if relation == 'direct':
                        op['targets'].append({'scope': target, 'relation': 'lexical_callee_candidate'})
                    else:
                        op['callback_values'].append({'scope': target, 'relation': 'passed_callable',
                                                      'invocation': 'not_established'})
        elif kind.startswith(('member_', 'subscript_')):
            member = next((ast.child_by_field_name(f) for f in ('attribute', 'field', 'property')
                           if ast.child_by_field_name(f) is not None), None)
            op['name'] = graph.text(member) if member is not None else '[]'
            base = _member_base(ast)
            if base is not None:
                op['receiver'] = self._port(base, 'receiver', statement)
            if kind.startswith('subscript_'):
                index = ast.child_by_field_name('subscript') or ast.child_by_field_name('index')
                if index is not None:
                    op['arguments'].append(self._port(index, 'index', statement))
            if kind.endswith('_write'):
                operator = parent.child_by_field_name('operator')
                op['assignment_operator'] = graph.text(operator) if operator is not None else '='
                value = parent.child_by_field_name('right') or parent.child_by_field_name('value')
                if value is not None:
                    op['arguments'].append(self._port(value, 'written_value', statement))
            op['unknowns'].append('member_access_effects_and_dynamic_dispatch')
        elif kind == 'annotation':
            op['name'] = graph.text(ast.named_children[0])
            op['arguments'] = [self._port(c, f'annotation:{i}', statement)
                               for i, c in enumerate(ast.named_children[1:])]
            op['unknowns'].append('compile_time_attribute_semantics')
        elif kind in {'return', 'yield', 'await'}:
            op['name'] = kind
            op['arguments'] = [self._port(c, f'value:{i}', statement)
                               for i, c in enumerate(ast.named_children) if c.type != 'comment']
            if kind in {'yield', 'await'}:
                op['unknowns'].append('suspension_resumption_not_observed')
        else:
            op['name'] = 'assert'
            op['arguments'] = [self._port(c, f'positional:{i}', statement) for i, c in enumerate(ast.named_children)]
            op['observation'] = {'kind': 'assertion', 'inputs': ['positional:0'],
                                 'timing': 'after_condition_evaluation', 'reached': 'not_established'}
            if len(op['arguments']) > 1:
                op['unknowns'].append('assert_message_evaluated_only_on_failure')
        if any(f['kind'] == 'loop' for f in frames):
            op['unknowns'].append('dynamic_iteration_identity')
        if any(f['kind'] == 'expression_condition' for f in frames):
            op['unknowns'].append('expression_path_condition')
        self.operations.append(op)
        self.by_scope[op['scope']].append(op)
        self._by_statement[statement].append(op)
        self._operation_by_ast[ast.id] = op

    def _index_definitions(self):
        graph = self.graph
        represented = set()
        self._definition_values = {}
        for ast, statement, frames in self._assignments:
            left = ast.child_by_field_name('left') or ast.child_by_field_name('name') or ast.child_by_field_name('pattern')
            right = _unwrap(ast.child_by_field_name('right') or ast.child_by_field_name('value'))
            left = _unwrap(left)
            if left is None:
                continue
            names = graph._names(left)
            operator = ast.child_by_field_name('operator')
            augmented = operator is not None and operator.type not in {'=', ':=', ':'}
            simple = left.type in IDENTS and right is not None and not augmented
            for name in names:
                binding = graph._binding(graph.nodes[statement]['scope'], name)
                definition = self._definition(statement, binding, left, ast.end_byte)
                represented.add((statement, binding))
                definition['value_range'] = _span(right) if right is not None else None
                definition['value_kind'] = 'unresolved'
                if any(frame['kind'] == 'loop' for frame in frames):
                    definition['unknowns'].append('dynamic_iteration_identity')
                if any(frame['kind'] == 'expression_condition' for frame in frames):
                    definition['unknowns'].append('conditional_expression_definition')
                if augmented:
                    definition['unknowns'].append('augmented_assignment_result_identity')
                if simple:
                    if right.type in IDENTS and self.suffix in REFERENCE_LANGUAGES:
                        definition['value_kind'] = 'direct_reference'
                    elif right.type in FRESH['.py' if self.suffix == '.py' else '.js'] and self.suffix in REFERENCE_LANGUAGES:
                        definition['value_kind'] = 'fresh_allocation'
                    elif right.type in CALLS:
                        definition['value_kind'] = 'call_result'
                    elif right.type in STRINGS | {'integer', 'int_literal', 'float', 'float_literal', 'number', 'true', 'false', 'none', 'nil', 'boolean_literal'}:
                        definition['value_kind'] = 'literal'
                    elif right.type in IDENTS:
                        definition['unknowns'].append('value_assignment_does_not_establish_object_alias')
                elif not augmented:
                    definition['unknowns'].append('destructuring_or_multiple_assignment')
                self._definition_values[definition['id']] = right
                # A single call also supplies destructured/multiple results.
                # This is a dependency, not an identity claim about the outputs.
                if right is not None and right.id in self._operation_by_ast:
                    self._operation_by_ast[right.id]['result']['definitions'].append(definition['id'])
        for node in graph.nodes:
            for binding in sorted(node['defs']):
                if (node['id'], binding) not in represented:
                    definition = self._definition(node['id'], binding, node['ast'], node['end'])
                    definition['unknowns'].append('definition_value_not_modeled')
        for scope in graph.scopes:
            for name in sorted(scope['params']):
                identity = f'{self.source}:parameter:{scope["id"]}:{name}'
                definition = {'id': identity, 'binding': [scope['id'], name], 'statement': scope['header'],
                              'range': _span(scope['ast']), 'available_after': scope['ast'].start_byte,
                              'value_range': None, 'value_kind': 'parameter', 'source_versions': [],
                              'value_identity': identity, 'identity_kind': 'symbolic_value',
                              'unknowns': ['argument_binding_not_established']}
                self.definitions.append(definition)
                self._definition_by_id[identity] = definition
                self._parameters_by_scope[scope['id']][(scope['id'], name)] = {identity}

    def _definition(self, statement, binding, ast, available_after):
        identity = f'{self.source}:definition:{statement}:{ast.start_byte}:{binding[0]}:{binding[1]}'
        definition = {'id': identity, 'binding': list(binding), 'statement': statement, 'range': _span(ast),
                      'available_after': available_after, 'value_range': None, 'value_kind': 'unresolved',
                      'source_versions': [], 'value_identity': None, 'identity_kind': 'unresolved', 'unknowns': []}
        self.definitions.append(definition)
        self._definition_by_id[identity] = definition
        self._definitions_by_statement[statement].append(definition)
        return definition

    def _reaching_definitions(self):
        graph = self.graph
        for scope in graph.scopes:
            ids = scope['nodes']
            if not ids:
                continue
            successors = defaultdict(set)
            for statement in ids:
                for pred in graph.nodes[statement]['pred']:
                    successors[pred].add(statement)
            pending = [ids[0]]
            reachable = set()
            while pending:
                statement = pending.pop()
                if statement in reachable:
                    continue
                reachable.add(statement)
                pending.extend(successors[statement] - reachable)
            self.reachable.update(reachable)
            parameters = self._parameters_by_scope[scope['id']]
            outgoing = {i: {} for i in ids}
            queue, queued = deque(sorted(reachable)), set(reachable)
            while queue:
                statement = queue.popleft()
                queued.remove(statement)
                incoming = defaultdict(set)
                if statement == ids[0]:
                    for binding, versions in parameters.items():
                        incoming[binding].update(versions)
                for pred in graph.nodes[statement]['pred'] & reachable:
                    for binding, versions in outgoing[pred].items():
                        incoming[binding].update(versions)
                self._incoming[statement] = incoming
                current = {binding: set(versions) for binding, versions in incoming.items()}
                for definition in sorted(self._definitions_by_statement[statement], key=lambda d: d['available_after']):
                    binding = tuple(definition['binding'])
                    if 'conditional_expression_definition' in definition['unknowns']:
                        current.setdefault(binding, set()).add(definition['id'])
                    else:
                        current[binding] = {definition['id']}
                if current != outgoing[statement]:
                    outgoing[statement] = current
                    for nxt in successors[statement] - queued:
                        queue.append(nxt)
                        queued.add(nxt)
        resolving, resolved = set(), set()

        def resolve(definition):
            identity = definition['id']
            if identity in resolved or definition['value_kind'] == 'parameter':
                return
            if identity in resolving:
                definition['unknowns'].append('cyclic_definition_identity')
                return
            resolving.add(identity)
            kind = definition['value_kind']
            if kind == 'direct_reference':
                value = self._definition_values[identity]
                statement = definition['statement']
                binding = graph._binding(graph.nodes[statement]['scope'], graph.text(value))
                versions = self._versions(statement, value.start_byte, binding)
                definition['source_versions'] = sorted(versions)
                for version in versions:
                    resolve(self._definition_by_id[version])
                values = {self._definition_by_id[v]['value_identity'] for v in versions}
                if len(values) == 1 and None not in values:
                    definition['value_identity'] = values.pop()
                    definition['identity_kind'] = self._definition_by_id[next(iter(versions))]['identity_kind']
                else:
                    definition['unknowns'].append('reference_identity_not_unique')
            elif kind in {'fresh_allocation', 'call_result', 'literal'}:
                definition['value_identity'] = identity
                definition['identity_kind'] = 'fresh_allocation' if kind == 'fresh_allocation' else 'symbolic_value'
                if kind == 'call_result':
                    definition['unknowns'].append('return_value_may_alias_other_values')
            if {'dynamic_iteration_identity', 'conditional_expression_definition'} & set(definition['unknowns']):
                definition['value_identity'] = None
                definition['identity_kind'] = 'unresolved'
            resolving.remove(identity)
            resolved.add(identity)

        for definition in self.definitions:
            resolve(definition)
        for op in self.operations:
            op['reachability'] = 'reachable_within_frame' if op['statement'] in self.reachable else 'unreachable_within_frame'

    def _versions(self, statement, position, binding):
        scope = self.graph.nodes[statement]['scope']
        if binding[0] != scope or binding in self._rebindable_cells:
            return set()  # Lexical cell identity is known; its value at invocation is not.
        versions = set(self._incoming.get(statement, {}).get(binding, ()))
        for definition in sorted(self._definitions_by_statement[statement], key=lambda d: d['available_after']):
            if tuple(definition['binding']) == binding and definition['available_after'] <= position:
                if 'conditional_expression_definition' in definition['unknowns']:
                    versions.add(definition['id'])
                else:
                    versions = {definition['id']}
        return versions

    def _bind_ports(self):
        starts = {statement: [node.start_byte for node in nodes]
                  for statement, nodes in self._identifier_reads.items()}
        producers = defaultdict(lambda: defaultdict(list))
        for op in self.operations:
            producers[op['statement']][tuple(op['expression_range'])].append(op['id'])
        for op in self.operations:
            ports = [*op['arguments']]
            if op['callee'] is not None:
                ports.append(op['callee'])
            if op['receiver'] is not None:
                ports.append(op['receiver'])
            for port in ports:
                # Keep references inside compound checks (assert a == b), as
                # well as their complete expression; no per-view AST walk.
                port['reads'] = []
                nodes = self._identifier_reads[op['statement']]
                at = bisect_left(starts.get(op['statement'], []), port['range'][0])
                for position in range(at, len(nodes)):
                    node = nodes[position]
                    if node.start_byte >= port['range'][1]:
                        break
                    read = self._port(node, 'value_read', op['statement'])
                    self._bind_reference(read, op)
                    port['reads'].append(read)
                if port['binding'] is None:
                    port['producer_operations'] = producers[op['statement']][tuple(port['range'])]
                    continue
                self._bind_reference(port, op)
            if op['observation'] is not None:
                op['observation']['expression_range'] = op['expression_range']
                op['observation']['effects'] = 'not_assumed_pure'

    def _bind_reference(self, port, op):
        binding = tuple(port['binding'])
        if binding[0] != op['scope']:
            port['unknowns'].append('lexical_cell_value_at_invocation')
            port['lexical_cell'] = list(binding)
        if binding in self._rebindable_cells:
            port['unknowns'].append('lexical_cell_can_be_rebound_by_another_frame')
        versions = self._versions(op['statement'], port['range'][0], binding)
        # Python evaluates the RHS before resolving an attribute assignment's
        # base. Text position alone cannot bind a base also rebound in that RHS.
        write_rebindings = []
        if self.suffix == '.py' and op['kind'] in {'member_write', 'subscript_write'}:
            write_rebindings = [d for d in self._definitions_by_statement[op['statement']]
                                if tuple(d['binding']) == binding and d['available_after'] > port['range'][1]]
        if write_rebindings:
            versions.update(d['id'] for d in write_rebindings)
            port['unknowns'].append('assignment_evaluation_order_rebinding')
        port['definition_versions'] = sorted(versions)
        values = {self._definition_by_id[v]['value_identity'] for v in versions}
        if len(values) == 1 and None not in values and not write_rebindings:
            port['value_identity'] = values.pop()
            port['identity_kind'] = self._definition_by_id[next(iter(versions))]['identity_kind']
        elif versions:
            port['unknowns'].append('multiple_or_unresolved_reaching_values')
        else:
            port['unknowns'].append('no_local_reaching_definition')

    def _index_order(self):
        # Containment alone is insufficient: a lambda body is a different frame.
        for operations in self._by_statement.values():
            ast_operations = sorted(operations, key=lambda op: (op['expression_range'][0], -op['expression_range'][1]))
            stack = []
            for op in ast_operations:
                start, end = op['expression_range']
                while stack and not (stack[-1]['expression_range'][0] <= start and end <= stack[-1]['expression_range'][1]):
                    stack.pop()
                if stack:
                    self.order.append({'before': op['id'], 'after': stack[-1]['id'],
                                       'kind': 'operand_evaluation', 'condition': 'both_events_reached_in_same_activation'})
                stack.append(op)
        for op in self.operations:
            if op['kind'] in {'member_write', 'subscript_write'}:
                for argument in op['arguments']:
                    for producer in argument.get('producer_operations', []):
                        self.order.append({'before': producer, 'after': op['id'], 'kind': 'write_value_evaluation',
                                           'condition': 'both_events_reached_in_same_activation'})

    def _index_effects(self):
        """Keep explicit access and possible call effects separate.

        Targets refer to existing ports, so aliases, guards and raw expressions
        remain available without another heap model or a guessed postcondition.
        """
        for op in self.operations:
            if op['kind'].startswith(('member_', 'subscript_')):
                write = op['kind'].endswith('_write')
                effect = ('read_write' if write and op['assignment_operator'] not in {'=', ':='}
                          else 'write' if write else 'read')
                self.effects.append({'operation': op['id'], 'scope': op['scope'],
                                     'kind': effect,
                                     'target': 'receiver', 'field': op['name'],
                                     'certainty': 'syntactic_access',
                                     'condition': 'if_reached_in_the_same_activation'})
            elif op['kind'] == 'call':
                roles = [p['role'] for p in op['arguments']]
                if op['receiver'] is not None:
                    roles.append('receiver')
                for role in roles:
                    self.effects.append({'operation': op['id'], 'scope': op['scope'],
                                         'kind': 'may_read_write', 'target': role,
                                         'certainty': 'unknown_callee_effect',
                                         'condition': 'if_called'})
                self.effects.append({'operation': op['id'], 'scope': op['scope'],
                                     'kind': 'may_read_write', 'target': 'external_state',
                                     'certainty': 'unknown_callee_effect', 'condition': 'if_called'})

    def _index_cells(self):
        captures = defaultdict(list)
        for op in self.operations:
            ports = (op['arguments'] + ([op['receiver']] if op['receiver'] is not None else [])
                     + ([op['callee']] if op['callee'] is not None else []))
            for port in ports:
                for read in port['reads']:
                    if 'lexical_cell' in read:
                        captures[tuple(read['lexical_cell'])].append({'operation': op['id'],
                                                                   'range': read['range']})
        for definition in self.definitions:
            statement = definition['statement']
            if statement is not None and definition['binding'][0] != self.graph.nodes[statement]['scope']:
                captures[tuple(definition['binding'])]
        for binding, uses in sorted(captures.items()):
            self.cells.append({'binding': list(binding), 'uses': uses,
                               'definitions': [d['id'] for d in self.definitions
                                               if tuple(d['binding']) == binding],
                               'identity': 'shared_lexical_binding_per_defining_activation',
                               'unknowns': ['defining_activation_and_value_at_invocation']})

    def view(self, node_ids):
        selected = set(node_ids)
        operations = [op for statement in sorted(selected) for op in self._by_statement[statement]]
        ids = {op['id'] for op in operations}
        definitions = [d for statement in sorted(selected) for d in self._view_definitions_by_statement[statement]]
        scopes = {self.graph.nodes[n]['scope'] for n in selected}
        for scope in list(scopes):
            parent = self.graph.scopes[scope]['parent']
            while parent is not None:
                scopes.add(parent)
                parent = self.graph.scopes[parent]['parent']
        return {'source': self.source, 'operations': operations, 'definitions': definitions,
                'scopes': [{'id': s['id'], 'name': s['name'], 'kind': s['kind'], 'parent': s['parent'],
                            'range': _span(s['ast'])} for s in self.graph.scopes if s['id'] in scopes],
                'order': [edge for op in operations for edge in self._order_by_before[op['id']] if edge['after'] in ids],
                'effects': [effect for op in operations for effect in self._effects_by_operation[op['id']]],
                'cells': [cell for cell in self.cells if any(use['operation'] in ids for use in cell['uses'])
                          or any(d['id'] in cell['definitions'] for d in definitions)],
                'cfg': [{'before': pred, 'after': statement, 'kind': 'static_cfg',
                         'certainty': 'may_flow'} for statement in sorted(selected)
                        for pred in sorted(self.graph.nodes[statement]['pred'] & selected)],
                'issues': list(self.issues),
                'limitations': ['Static reachability is conditional on invoking the containing frame.',
                                'Effects, exceptions, callbacks, and loop iteration identities are unresolved.',
                                'Different symbolic values do not prove distinct objects.',
                                'CFG exception/cleanup paths are inherited approximations; no runtime reachability claim.',
                                'Embedded languages and macro expansion are not interpreted.']}
