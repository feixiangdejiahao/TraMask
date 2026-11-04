"""Research slicer: scoped definitions, CFG reaching definitions and state order.

Slices retain source statements and dependency edges, not an executable rewrite.
Unknown calls have possible receiver/argument effects. Embedded programs remain
opaque inputs. These approximations are exported for the pilot to assess.
"""
from collections import defaultdict, deque
from pathlib import PurePosixPath
import re

from .anchors import FUNCTIONS, STRINGS, _parser, _call_name
from .pre_slice import ANONYMOUS, merge_ranges

FUNCTION_NODES = FUNCTIONS | ANONYMOUS
CLASS_NODES = {'class_definition', 'class_declaration', 'struct_item', 'impl_item', 'mod_item'}
BLOCKS = {'module', 'source_file', 'program', 'block', 'statement_block', 'statement_list',
          'class_body', 'declaration_list'}
CONTROL = {'if_statement', 'elif_clause', 'else_clause', 'for_statement', 'while_statement',
           'do_statement', 'for_in_statement', 'for_expression', 'while_expression',
           'if_expression', 'match_expression', 'switch_statement', 'expression_switch_statement',
           'type_switch_statement', 'select_statement', 'try_statement', 'except_clause',
           'catch_clause', 'finally_clause', 'with_statement', 'match_statement',
           'case_clause', 'case_statement', 'switch_case', 'match_arm', 'communication_case',
           'expression_case', 'type_case'}
LOOPS = {'for_statement', 'while_statement', 'do_statement', 'for_in_statement', 'for_expression', 'while_expression'}
CALLS = {'call', 'call_expression', 'new_expression', 'macro_invocation'}
MEMBERS = {'attribute', 'selector_expression', 'member_expression', 'field_expression'}
IDENTS = {'identifier', 'field_identifier', 'property_identifier', 'type_identifier', 'package_identifier',
          'shorthand_property_identifier', 'self'}
ASSIGN = {'assignment', 'augmented_assignment', 'named_expression', 'assignment_statement',
          'assignment_expression', 'augmented_assignment_expression',
          'short_var_declaration', 'let_declaration', 'variable_declarator', 'var_spec',
          'const_spec', 'const_item', 'static_item'}
SKIP = {'comment', 'line_comment', 'block_comment', 'empty_statement'}
PURE = {'len', 'str', 'int', 'float', 'bool', 'repr', 'hash', 'type', 'isinstance', 'issubclass',
        'range', 'enumerate', 'zip', 'min', 'max', 'sum', 'abs', 'round', 'format', 'all', 'any'}
OBS = re.compile(r'^(?:assert|Assert|require|Require|expect|Expect|print|Print|printf|Printf|println|Println|log|Log|Fatal|Errorf|Equal|NotEqual|True|False|toBe|toEqual|toStrictEqual|toThrow|is$|throws)')


def _subtract(start, end, holes):
    result, at = [], start
    for a, b in sorted(holes):
        if a > at:
            result.append([at, a])
        at = max(at, b)
    if at < end:
        result.append([at, end])
    return result


def strongly_connected_components(nodes, successors):
    predecessors=defaultdict(set)
    for node in nodes:
        for nxt in successors[node]:predecessors[nxt].add(node)
    seen,order=set(),[]
    for start in nodes:
        if start in seen:continue
        todo=[(start,False)]
        while todo:
            node,done=todo.pop()
            if done:order.append(node);continue
            if node in seen:continue
            seen.add(node);todo.append((node,True))
            todo.extend((n,False) for n in successors[node] if n not in seen)
    components={}
    for start in reversed(order):
        if start in components:continue
        todo=[start]
        while todo:
            node=todo.pop()
            if node in components:continue
            components[node]=start;todo.extend(predecessors[node])
    return components


class SourceGraph:
    def __init__(self, source, *, source_error=None):
        self.source = source
        self.raw = source['raw']
        self.root = None
        self.nodes, self.scopes = [], []
        self.test_definitions = None
        self.scope_nodes = {}
        self.callees = defaultdict(set)
        self.call_sites=defaultdict(list)
        self.issues = []
        self.header_scopes={};self.components={};self.slice_cache={}
        self.behavior_index = None
        self.relation_index = None
        if source_error is not None:
            self.issues.append({'kind':'source_encoding_error','source':source['id'],'reason':source_error})
            return
        self.root = _parser(PurePosixPath(source['path']).suffix).parse(self.raw).root_node
        if self.root.has_error:
            self.issues.append({'kind': 'source_parse_error', 'source': source['id']})
            return
        self._new_scope(self.root, None, '<module>', 'module', None)
        self._emit_block(self.root, 0, set(), ())
        self._bind_names()
        self._flow()
        self._link_calls()
        self.header_scopes = {s['header']:s['id'] for s in self.scopes if s['header'] is not None}
        self.components, self.slice_cache = {}, {}

    def text(self, node):
        return self.raw[node.start_byte:node.end_byte].decode() if node is not None else ''

    def _new_scope(self, ast, parent, name, kind, header):
        sid = len(self.scopes)
        self.scope_nodes[ast.id] = sid
        self.scopes.append({'id': sid, 'ast': ast, 'parent': parent, 'name': name, 'kind': kind,
                            'header': header, 'nodes': [], 'locals': set(), 'params': set(), 'returns': set(),
                            'globals':set(),'nonlocals':set(),'binding_declarations':set(),'parameter_order':[],
                            'parameter_kinds':{},
                            'cleanup':set()})
        return sid

    def _names(self, node):
        if node is None:
            return []
        if node.type in IDENTS:
            return [self.text(node)]
        if node.type in STRINGS or node.type in {'type_annotation', 'predefined_type', 'pointer_type', 'qualified_type'}:
            return []
        if node.type in MEMBERS | {'subscript', 'subscript_expression', 'index_expression'}:
            return []
        return [name for child in node.named_children for name in self._names(child)]

    def _atom(self, node, scope, preds, controls, kind=None, ranges=None):
        identity = len(self.nodes)
        item = {'id': identity, 'scope': scope, 'ast': node, 'start': node.start_byte, 'end': node.end_byte,
                'ranges': ranges if ranges is not None else [[node.start_byte, node.end_byte]],
                'kind': kind or node.type, 'pred': set(preds), 'control': set(controls),
                'data': set(), 'state': set(), 'uses': set(), 'defs': set(),
                'read_names': set(), 'def_names': set(), 'calls': [], 'aliases': [], 'state_names': set(),
                'scalar_defs': set(), 'callback_scopes': set(), 'callable_defs': {},
                'assign_names': set(), 'source_values': [], 'escapes': [], 'observation': False}
        self.nodes.append(item)
        self.scopes[scope]['nodes'].append(identity)
        return identity

    def _children(self, node):
        for child in node.named_children:
            if child.type == 'statement_list':
                yield from child.named_children
            else:
                yield child

    def _emit_block(self, node, scope, incoming, controls):
        tails = set(incoming)
        for child in self._children(node):
            if child.type in SKIP:
                continue
            tails = self._emit(child, scope, tails, controls)
        return tails

    def _emit(self, node, scope, incoming, controls):
        if node.type in BLOCKS:
            return self._emit_block(node, scope, incoming, controls)
        if node.type == 'decorated_definition':
            definition = node.child_by_field_name('definition')
            tails=self._emit(definition, scope, incoming, controls)
            header=self.nodes[self.scopes[self.scope_nodes[definition.id]]['header']]
            header['start']=node.start_byte
            for decorator in node.named_children:
                if decorator!=definition:
                    header['ranges'].append([decorator.start_byte,decorator.end_byte])
                    self._scan(header,decorator)
            return tails
        if node.type in FUNCTION_NODES | CLASS_NODES:
            body = node.child_by_field_name('body')
            if body is None:
                identity = self._atom(node, scope, incoming, controls, 'declaration')
                name=node.child_by_field_name('name')
                if name is not None:self.nodes[identity]['def_names'].add(self.text(name))
                for child in node.named_children:
                    self._scan(self.nodes[identity],child)
                return {identity}
            name_node = node.child_by_field_name('name')
            if name_node is None and node.parent is not None and node.parent.type == 'variable_declarator':
                name_node = node.parent.child_by_field_name('name')
            name = self.text(name_node) or '<callback@' + str(node.start_byte) + '>'
            header = self._atom(node, scope, incoming, controls, 'function' if node.type in FUNCTION_NODES else 'class',
                                [[node.start_byte, body.start_byte]])
            attribute=node.prev_named_sibling
            while attribute is not None and attribute.type=='attribute_item':
                self.nodes[header]['ranges'].append([attribute.start_byte,attribute.end_byte])
                self._scan(self.nodes[header],attribute)
                attribute=attribute.prev_named_sibling
            if name_node is not None:
                self.nodes[header]['def_names'].add(name)
            kind = 'function' if node.type in FUNCTION_NODES else 'class'
            sid = self._new_scope(node, scope, name, kind, header)
            params = node.child_by_field_name('parameters')
            if params is not None:
                keyword_only=False
                for parameter in params.named_children:
                    if parameter.type=='positional_separator':
                        for name in self.scopes[sid]['parameter_order']:self.scopes[sid]['parameter_kinds'][name]='positional_only'
                        continue
                    if parameter.type=='keyword_separator':keyword_only=True;continue
                    binding = (parameter.child_by_field_name('name') or parameter.child_by_field_name('pattern')
                               or (parameter if parameter.type in IDENTS else None))
                    if binding is None and parameter.type in {'typed_parameter','default_parameter','typed_default_parameter'}:
                        binding = parameter.named_children[0]
                    if parameter.type in {'list_splat_pattern','dictionary_splat_pattern'}:binding=parameter
                    names=self._names(binding)
                    self.scopes[sid]['params'].update(names)
                    self.scopes[sid]['parameter_order'].extend(names)
                    kind=('var_positional' if binding is not None and binding.type=='list_splat_pattern' else
                          'var_keyword' if binding is not None and binding.type=='dictionary_splat_pattern' else
                          'keyword_only' if keyword_only else 'positional_or_keyword')
                    for name in names:self.scopes[sid]['parameter_kinds'][name]=kind
                    if kind=='var_positional':keyword_only=True
            receiver = node.child_by_field_name('receiver')
            if receiver is not None:
                self.scopes[sid]['params'].update(self._names(receiver))
            if body.type in BLOCKS:
                self._emit_block(body, sid, set(), ())
            else:
                rid = self._atom(body, sid, set(), (), 'return')
                self._scan(self.nodes[rid], body)
                self.scopes[sid]['returns'].add(rid)
            return {header}
        # Rust control expressions are wrapped as expression statements.
        if node.type == 'expression_statement' and len(node.named_children) == 1 and node.named_children[0].type in CONTROL:
            return self._emit(node.named_children[0], scope, incoming, controls)
        if node.type in {'if_statement', 'if_expression', 'elif_clause'}:
            # Each condition has a false continuation; the condition itself
            # must not survive a final else when every branch exits. Python's
            # elif/else are sibling alternatives, unlike nested JS/Go/Rust ifs.
            branches = [node, *node.children_by_field_name('alternative')]
            tails, false_path = set(), set(incoming)
            branch_controls = controls
            for branch in branches:
                if branch != node and branch.type != 'elif_clause':
                    tails.update(self._emit(branch, scope, false_path, branch_controls))
                    false_path = set()
                    continue
                body = branch.child_by_field_name('consequence')
                holes = [(body.start_byte, body.end_byte)]
                holes.extend((a.start_byte, a.end_byte) for a in branch.children_by_field_name('alternative'))
                identity = self._atom(branch, scope, false_path, branch_controls, 'control',
                                      _subtract(branch.start_byte, branch.end_byte, holes))
                for child in branch.named_children:
                    if child != body and child not in branch.children_by_field_name('alternative'):
                        self._scan(self.nodes[identity], child)
                branch_controls = (*branch_controls, identity)
                tails.update(self._emit(body, scope, {identity}, branch_controls))
                false_path = {identity}
            return tails | false_path
        if node.type == 'else_clause':
            identity = self._atom(node, scope, incoming, controls, 'control',
                                  _subtract(node.start_byte, node.end_byte,
                                            [(c.start_byte, c.end_byte) for c in node.named_children]))
            return self._emit_block(node, scope, {identity}, (*controls, identity))
        if node.type in CONTROL:
            blocks = [c for c in node.named_children if c.type in BLOCKS | CONTROL
                      or c.type in {'case_clause', 'match_block', 'switch_body'}]
            # Header expressions remain separate from controlled bodies.
            holes = [(c.start_byte, c.end_byte) for c in blocks]
            identity = self._atom(node, scope, incoming, controls, 'control', _subtract(node.start_byte, node.end_byte, holes))
            item = self.nodes[identity]
            for child in node.named_children:
                if child not in blocks:
                    self._scan(item, child)
            if node.type == 'try_statement':
                normal = set()
                throwing = set()
                handlers, finals = [], []
                for block in blocks:
                    if block.type in {'except_clause','catch_clause'}:
                        handlers.append(block)
                    elif block.type == 'finally_clause':
                        finals.append(block)
                    else:
                        before = len(self.nodes)
                        normal.update(self._emit_block(block, scope, {identity}, (*controls,identity)))
                        throwing.update(n['id'] for n in self.nodes[before:] if n['scope']==scope and n['calls'])
                tails = set(normal)
                for handler in handlers:
                    tails.update(self._emit(handler,scope,{identity}|throwing,(*controls,identity,*sorted(throwing))))
                for final in finals:
                    tails = self._emit(final,scope,tails,(*controls,identity))
                return tails | {identity}
            if node.type in LOOPS:
                clause = next((c for c in node.named_children if c.type in {'range_clause', 'for_in_clause'}), None)
                binding = node.child_by_field_name('left') or node.child_by_field_name('pattern')
                if clause is not None:
                    binding = clause.child_by_field_name('left')
                item['def_names'].update(self._names(binding))
            tails = set()
            for block in blocks:
                if block.type in BLOCKS:
                    tails.update(self._emit_block(block, scope, {identity}, (*controls, identity)))
                else:
                    tails.update(self._emit(block, scope, {identity}, (*controls, identity)))
            if node.type in LOOPS:
                item['pred'].update(tails)
                return {identity}
            # Both arms may continue; missing else preserves the entry arm.
            return tails | {identity}
        # Declarations with several values are one executable statement.
        identity = self._atom(node, scope, incoming, controls)
        self._scan(self.nodes[identity], node)
        if node.type=='defer_statement':self.scopes[scope]['cleanup'].add(identity)
        terminal = (node.named_children[0] if node.type == 'expression_statement' and
                    len(node.named_children) == 1 else node)
        if terminal.type in {'return_statement', 'return_expression', 'raise_statement', 'throw_statement'}:
            self.nodes[identity]['kind'] = 'return' if terminal.type.startswith('return') else 'raise'
            self.scopes[scope]['returns'].add(identity)
            return set()
        return {identity}

    def _scan(self, item, node):
        todo=[('node',node,None)]
        while todo:
            action,current,names=todo.pop()
            if action=='bind_callable':
                for name in names:item['callable_defs'][name]=self.scope_nodes[current.id]
            else:
                todo.extend(reversed(self._scan_node(item,current)))

    def _scan_node(self, item, node):
        if node.type in SKIP:
            return []
        if node.type in {'global_statement','nonlocal_statement'}:
            scope=self.scopes[item['scope']]
            scope['globals' if node.type=='global_statement' else 'nonlocals'].update(self._names(node))
            scope['binding_declarations'].add(item['id'])
            return []
        if node.type in FUNCTION_NODES | CLASS_NODES:
            parent=node.parent
            if (parent is not None and parent.type in MEMBERS and
                    self.text(parent.child_by_field_name('property'))=='toString'):
                # This function supplies source text to a parser. Its body is
                # input data, not a callback executed by the surrounding test.
                item['source_values'].append([node.start_byte,node.end_byte])
                return []
            # Function-valued arguments are explicit callbacks, not flattened
            # statements in the caller's scope.
            self._emit(node, item['scope'], set(), ())
            sid = self.scope_nodes[node.id]
            self.scopes[sid]['creator'] = item['id']
            item['callback_scopes'].add(sid)
            item['data'].add(self.scopes[sid]['header'])
            item['ranges'] = [span for a, b in item['ranges'] for span in _subtract(a, b, [(node.start_byte, node.end_byte)])]
            return []
        if node.type in STRINGS:
            return [('node',nested,None) for child in node.named_children
                    if child.type in {'interpolation','template_substitution'} for nested in child.named_children]
        if node.type in {'inc_statement','dec_statement','update_expression'}:
            value=node.named_children[0]
            if value.type in IDENTS:
                item['assign_names'].add(self.text(value));item['read_names'].add(self.text(value))
            else:item['state_names'].update(self._base_names(value))
            return [('node',value,None)]
        if node.type in {'subscript','subscript_expression','index_expression'}:
            item['state_names'].update(self._base_names(node))
        if node.type in {'yield','yield_expression'}:
            item['kind']='yield'
            self.scopes[item['scope']]['returns'].add(item['id'])
        if node.type in ASSIGN:
            children=[]
            left = node.child_by_field_name('left') or node.child_by_field_name('name') or node.child_by_field_name('pattern')
            right = node.child_by_field_name('right') or node.child_by_field_name('value')
            names = set(self._names(left))
            # Python assignment binds locally; JS/Go reassignment uses an
            # existing lexical binding. Declarations still introduce locals.
            if node.type in {'assignment_expression','augmented_assignment_expression','assignment_statement'}:
                item['assign_names'].update(names)
            else:
                item['def_names'].update(names)
            if right is not None:
                if right.type in IDENTS:
                    item['aliases'].extend((name, self.text(right)) for name in names)
                if right.type in {'integer','int_literal','float','float_literal','number','true','false','none','nil','boolean_literal'} | STRINGS:
                    item['scalar_defs'].update(names)
                children.append(('node',right,None))
                value=right
                while value.type in {'expression_list','parenthesized_expression'} and len(value.named_children)==1:
                    value=value.named_children[0]
                if value.type in FUNCTION_NODES:
                    children.append(('bind_callable',value,names))
            annotation=node.child_by_field_name('type')
            if annotation is not None:children.append(('node',annotation,None))
            if left is not None and left.type in MEMBERS | {'subscript', 'subscript_expression', 'index_expression'}:
                children.append(('node',left,None))
                item['state_names'].update(self._base_names(left))
            if node.type in {'augmented_assignment', 'assignment_statement'} and ('+=' in self.text(node) or '-=' in self.text(node)):
                item['read_names'].update(names)
            return children
        if node.type in {'import_statement', 'import_from_statement', 'use_declaration', 'import_spec'}:
            item['kind'] = 'import'
            if node.type == 'import_spec':
                path = self.text(node.child_by_field_name('path')).strip('"`')
                alias = self.text(node.child_by_field_name('name')) or path.rsplit('/', 1)[-1]
                item['def_names'].add(alias)
            elif node.type == 'use_declaration':
                text = self.text(node).rstrip(';')
                item['def_names'].add(re.findall(r'\b\w+\b', text)[-1])
            else:
                for child in node.named_children:
                    if child.type == 'aliased_import':
                        item['def_names'].add(self.text(child.child_by_field_name('alias')))
                    elif node.type == 'import_from_statement' and node.child_by_field_name('module_name') == child:
                        continue
                    elif child.type == 'dotted_name':
                        item['def_names'].add(self.text(child).split('.')[0])
                    elif child.type == 'import_clause':
                        item['def_names'].update(self._names(child))
            return []
        if node.type == 'assert_statement':
            item['observation'] = True
            item['state_names'].update(self._value_names(node))
        if node.type in CALLS:
            name = _call_name(self.raw, node) if node.type != 'macro_invocation' else self.text(node.child_by_field_name('macro'))
            callee = node.child_by_field_name('function') or node.child_by_field_name('constructor')
            args = node.child_by_field_name('arguments')
            if node.type == 'macro_invocation':
                args = next((c for c in node.named_children if c.type=='token_tree'),None)
            item['calls'].append((name, callee, node))
            observation = bool(name and OBS.match(name))
            item['observation'] |= observation
            if observation and args is not None:
                item['state_names'].update(self._value_names(args))
            if not observation and name not in PURE:
                effect_names = set(item['def_names'])
                if callee is not None and callee.type in MEMBERS:
                    effect_names.update(self._base_names(callee))
                if args is not None:
                    effect_names.update(self._value_names(args))
                item['state_names'].update(effect_names)
                item['escapes'].append(effect_names)
        if node.type in MEMBERS:
            base = (node.child_by_field_name('object') or node.child_by_field_name('operand')
                    or node.child_by_field_name('value'))
            member = next((node.child_by_field_name(f) for f in ('attribute','field','property')
                           if node.child_by_field_name(f) is not None), None)
            if base is not None:
                item['state_names'].update(self._base_names(base))
                if base.type in {'identifier','self'} and self.text(base) in {'self','cls'} and member is not None:
                    item['read_names'].add('self.' + self.text(member))
            return [('node',base,None)] if base is not None else []
        if node.type in IDENTS:
            item['read_names'].add(self.text(node))
            return []
        return [('node',child,None) for child in node.named_children]

    def _base_names(self, node):
        while node is not None and node.type in MEMBERS | {'subscript','subscript_expression','index_expression'}:
            node = (node.child_by_field_name('object') or node.child_by_field_name('operand')
                    or node.child_by_field_name('value') or node.named_children[0])
        return {self.text(node)} if node is not None and node.type in IDENTS else set()

    def _value_names(self, node):
        result=set();todo=[node]
        while todo:
            current=todo.pop()
            if current.type in {'type_identifier','predefined_type','type_annotation','slice_type','array_type'}:continue
            if current.type in IDENTS:result.add(self.text(current))
            elif current.type in STRINGS|FUNCTION_NODES:continue
            elif current.type in MEMBERS:result.update(self._base_names(current))
            elif current.type in CALLS:
                args=current.child_by_field_name('arguments')
                callee=current.child_by_field_name('function') or current.child_by_field_name('constructor')
                if args is not None:todo.append(args)
                if callee is not None and callee.type in MEMBERS:result.update(self._base_names(callee))
            elif current.type in {'keyword_argument','pair','property_assignment','composite_literal','struct_expression'}:
                child=current.child_by_field_name('body' if current.type in {'composite_literal','struct_expression'} else 'value')
                if child is not None:todo.append(child)
            else:todo.extend(current.named_children)
        return result

    def _binding(self, scope, name):
        if name in self.scopes[scope]['globals']:return 0,name
        if name in self.scopes[scope]['nonlocals']:
            parent=self.scopes[scope]['parent']
            while parent is not None:
                if name in self.scopes[parent]['locals']|self.scopes[parent]['params']:return parent,name
                parent=self.scopes[parent]['parent']
        if name.startswith('self.'):
            parent = self.scopes[scope]['parent']
            while parent is not None:
                if self.scopes[parent]['kind'] == 'class':
                    return parent, name[5:]
                parent = self.scopes[parent]['parent']
        sid = scope
        while sid is not None:
            if name in self.scopes[sid]['locals'] | self.scopes[sid]['params']:
                return sid, name
            sid = self.scopes[sid]['parent']
        return 0, name

    def _bind_names(self):
        for node in self.nodes:
            scope=self.scopes[node['scope']]
            scope['locals'].update(node['def_names']-scope['globals']-scope['nonlocals'])
        self.definitions = defaultdict(set)
        for scope in self.scopes:
            if scope['header'] is not None:
                for name in scope['params']:
                    self.definitions[scope['id'], name].add(scope['header'])
        for node in self.nodes:
            node['defs'] = ({self._binding(node['scope'],name) for name in node['def_names']}
                            | {self._binding(node['scope'],name) for name in node['assign_names']})
            node['uses'] = {self._binding(node['scope'], name) for name in node['read_names']}
            for key in node['defs']:
                self.definitions[key].add(node['id'])
            if self.scopes[node['scope']]['globals']|self.scopes[node['scope']]['nonlocals']:
                node['data'].update(self.scopes[node['scope']]['binding_declarations']-{node['id']})
        # Scope-local may-alias components, preserving class binding identity.
        parent = {}
        def find(key):
            parent.setdefault(key, key)
            if parent[key] != key:
                parent[key] = find(parent[key])
            return parent[key]
        def union(a, b):
            a, b = find(a), find(b)
            if a != b:
                parent[b] = a
        scalar = {key for node in self.nodes for name in node['scalar_defs'] for key in [(node['scope'],name)]}
        namespaces = {key for key,definitions in self.definitions.items()
                      if any(self.nodes[i]['kind']=='import' for i in definitions)}
        harness = set()
        for scope in self.scopes:
            parameters = scope['ast'].child_by_field_name('parameters')
            if parameters is not None:
                for parameter in parameters.named_children:
                    type_node = parameter.child_by_field_name('type')
                    if type_node is not None and re.search(r'\btesting\.(?:T|B|F)\b',self.text(type_node)):
                        harness.update((scope['id'],name) for name in self._names(parameter.child_by_field_name('name')))
        for node in self.nodes:
            for a, b in node['aliases']:
                union((node['scope'],a), self._binding(node['scope'],b))
            for group in node['escapes']:
                names = {self._binding(node['scope'],n) for n in group
                         if n!='_' and self._binding(node['scope'],n) not in scalar | harness | namespaces}
                if names:
                    first = min(names)
                    for key in names:
                        union(first,key)
        for node in self.nodes:
            node['objects'] = {find(self._binding(node['scope'],name)) for name in node['state_names']
                               if name!='_' and self._binding(node['scope'],name) not in scalar | harness | namespaces}

    def _flow(self):
        self.forward = defaultdict(set)
        for scope in self.scopes:
            ids = scope['nodes']
            reaching = {i:{} for i in ids}
            pending, queued = deque(ids), set(ids)
            successors = defaultdict(set)
            for i in ids:
                for pred in self.nodes[i]['pred']:
                    successors[pred].add(i)
            while pending:
                i = pending.popleft();queued.discard(i)
                node = self.nodes[i]
                incoming = defaultdict(set)
                for pred in node['pred']:
                    for key, values in reaching[pred].items():
                        incoming[key].update(values)
                for key in node['uses']:
                    values = incoming[key]
                    if not values:
                        if key[0]!=scope['id'] or key[1] in scope['params']:
                            values = self.definitions[key]
                    node['data'].update(values - {i})
                for obj in node['objects']:
                    node['state'].update(incoming[('state',obj)] - {i})
                new = {key:set(values) for key,values in incoming.items() if values}
                for key in node['defs']:
                    new[key] = {i}
                for obj in node['objects']:
                    new['state',obj] = {i}
                if new != reaching[i]:
                    reaching[i] = new
                    for nxt in successors[i]:
                        if nxt not in queued:
                            pending.append(nxt);queued.add(nxt)
            for i in ids:
                node = self.nodes[i]
                for pred in node['data'] | node['state'] | node['control']:
                    self.forward[pred].add(i)

    def _link_calls(self):
        headers = {s['header']:s['id'] for s in self.scopes if s['kind']=='function'}
        def callable_targets(binding):
            targets=set()
            for definition in self.definitions[binding]:
                item=self.nodes[definition]
                if (definition in headers and binding ==
                        (item['scope'],self.scopes[headers[definition]]['name'])):
                    targets.add(headers[definition])
                if binding[1] in item['callable_defs']:
                    targets.add(item['callable_defs'][binding[1]])
            return targets
        for node in self.nodes:
            for name, callee, ast in node['calls']:
                if callee is not None and callee.type in IDENTS:
                    binding = self._binding(node['scope'], self.text(callee))
                    for target in callable_targets(binding):
                        self.callees[node['id']].add(target)
                        self.call_sites[node['id']].append((ast,target,'direct'))
                args = ast.child_by_field_name('arguments')
                if args is not None:
                    for value in self._value_names(args):
                        binding = self._binding(node['scope'],value)
                        for target in callable_targets(binding):
                            node['callback_scopes'].add(target)
                            self.call_sites[node['id']].append((ast,target,'callable_value'))
                for target in node['callback_scopes']:
                    definition=self.scopes[target]['ast']
                    if ast.start_byte<=definition.start_byte and definition.end_byte<=ast.end_byte:
                        self.call_sites[node['id']].append((ast,target,'callable_value'))
            self.callees[node['id']].update(node['callback_scopes'])

    def statement_at(self, start, end):
        owners = [n for n in self.nodes if n['start'] <= start and end <= n['end']
                  and any(a <= start < b for a,b in n['ranges'])]
        return min(owners, key=lambda n:n['end']-n['start'])['id'] if owners else None

    def criterion(self, start, end):
        if self.issues:return None
        ast = self.root.descendant_for_byte_range(start, end-1)
        if ast.type in MEMBERS and ast.parent is not None and ast.parent.type in CALLS:
            if ast.parent.child_by_field_name('function') == ast:
                ast = ast.parent
        statement = self.statement_at(ast.start_byte, ast.end_byte)
        if statement is None:
            return None
        kind = ('call' if ast.type in CALLS else 'input_string' if ast.type in STRINGS
                else 'field' if ast.type in MEMBERS else 'value')
        return {'node':statement, 'start':ast.start_byte, 'end':ast.end_byte, 'kind':kind}

    def slice(self, seed, *, forward=True, state=True, calls=True):
        root = self.nodes[seed]
        active_scope = root['scope']
        if seed in self.header_scopes and self.scopes[self.header_scopes[seed]]['kind']=='function':
            active_scope=self.header_scopes[seed]
        if forward:
            if state not in self.components:
                self.components[state] = self._forward_components(state)
            cache_key = (active_scope,self.components[state][seed],state,calls)
            if cache_key in self.slice_cache:
                return self.slice_cache[cache_key]
        # Follow only data and object-state effects forward. Definitions added
        # later for expected values do not become new forward-slicing seeds.
        front, seen = [seed], {seed}
        while front and forward:
            current = front.pop()
            for nxt in self.forward[current]:
                if self.nodes[nxt]['scope'] != active_scope:
                    continue
                is_data = current in self.nodes[nxt]['data'] | self.nodes[nxt]['control']
                if not is_data and not state:
                    continue
                if nxt not in seen:
                    seen.add(nxt);front.append(nxt)
        selected, bindings, unresolved = set(), set(), set()
        todo = list(seen | self.scopes[active_scope]['cleanup'])
        parent = active_scope
        while parent is not None:
            header=self.scopes[parent]['header']
            if header is not None:todo.append(header)
            parent=self.scopes[parent]['parent']
        # Callee bodies stay parametric. Each selected invocation retains its
        # own binding edge; no formal is linked to unrelated actual callers.
        # Recursive summaries reach a finite fixed point without enumerating
        # every call-stack path.
        while todo:
            current = todo.pop()
            if current in selected:
                continue
            selected.add(current)
            node = self.nodes[current]
            deps = node['data'] | node['control'] | (node['state'] if state else set())
            todo.extend(dep for dep in deps if dep != current)
            if not calls:
                continue
            for callee in self.callees[current]:
                kind='callable_value' if callee in node['callback_scopes'] else 'direct'
                bindings.add((current,callee,kind))
                if kind=='callable_value':unresolved.add('callable_arguments_not_observed')
                scope = self.scopes[callee]
                effects = scope['returns'] | scope['cleanup'] | {i for i in scope['nodes'] if self.nodes[i]['observation'] or self.nodes[i]['objects']}
                if scope['header'] is not None:effects.add(scope['header'])
                todo.extend(effects)
        # Registration text supplies a callback's lexical context without
        # executing every sibling callback registered by its enclosing suite.
        context=set()
        for i in selected:
            sid=self.nodes[i]['scope']
            while sid is not None:
                scope=self.scopes[sid]
                if 'creator' in scope:context.add(scope['creator'])
                sid=scope['parent']
        ranges = merge_ranges(span for i in selected | context for span in self.nodes[i]['ranges'])
        result = {'nodes':sorted(selected), 'bindings':[list(binding) for binding in sorted(bindings)], 'ranges':ranges,
                  'context_nodes':sorted(context-selected),
                  'observations':sorted(i for i in selected if self.nodes[i]['observation']),
                  'unresolved':sorted(unresolved)}
        if forward:
            self.slice_cache[cache_key] = result
        return result

    def _forward_components(self, state):
        """Equal forward SCCs have equal forward closures and slice results."""
        successors=defaultdict(set)
        for node in self.nodes:
            deps=node['data']|node['control']|(node['state'] if state else set())
            for pred in deps:
                if self.nodes[pred]['scope']==node['scope']:
                    successors[pred].add(node['id'])
        return strongly_connected_components(range(len(self.nodes)),successors)

    def export_nodes(self):
        return [{'id':n['id'],'scope':n['scope'],'kind':n['kind'],'ranges':n['ranges'],
                 'data':sorted(n['data']),'control':sorted(n['control']),'state':sorted(n['state']),
                 'callees':sorted(self.callees[n['id']]),'callback_scopes':sorted(n['callback_scopes']),
                 'source_values':n['source_values'],
                 'observation':n['observation']}
                for n in self.nodes]
