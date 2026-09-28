"""Source-derived refinement of Python regex captures into split fields.

This module never runs subject code. A small, binding-aware source interpreter
tracks match objects, capture strings and literal-delimiter split lists. Tests
supply all values; the isolated regex matcher and a closed split evaluator check
each proposed leaf replacement. All emitted cells remain runtime hypotheses.
"""
from __future__ import annotations

import ast
from collections import Counter, defaultdict, deque
from dataclasses import asdict, dataclass, replace

from anchor_retrieval.syntax import Source
from generic_composition.corpus import source_text
from generic_composition.engine import stable_id

from .embedded_relations import format_source_string
from .regex_cells import (RegexBudget, _SourceFacts, _finite, _flow, _match,
                          _patterns, _position, _proximity, _row_edits,
                          _same_other_coordinates)
from .structured_ports import carrier_ports, structural_slot_key


@dataclass(frozen=True)
class ParsedFieldBudget(RegexBudget):
    max_attempts: int = 2048
    max_split_depth: int = 6
    max_analysis_nodes: int = 8192
    max_unknowns: int = 128
    max_call_depth: int = 3


@dataclass(frozen=True)
class _Value:
    kind: str
    group: int | str | None = None
    steps: tuple = ()
    evidence: tuple = ()
    parent: object = None
    delimiter: str | None = None
    maxsplit: int = -1
    constant: object = None
    group_arity: int | None = None


def _path_key(value):
    return value.group, tuple(step[:4] for step in value.steps), value.group_arity


def _semantic_path(value):
    return tuple(step[:3] for step in value.steps)


class _CaptureFlow:
    """Sequential local bindings; branch merges never guess a definition."""

    def __init__(self, fact, pattern, budget, unknowns, context=None, stack=()):
        self.fact, self.pattern, self.budget = fact, pattern, budget
        self.unknowns, self.found = unknowns, {}
        self.remaining = budget.max_analysis_nodes
        self.exhausted = False
        self.invalid_values = {}
        self.control_regions = []
        self.context, self.stack = context or {}, stack
        self.returns, self.call_evidence = [], []

    def unknown(self, kind, node):
        if len(self.unknowns) < self.budget.max_unknowns:
            row = {'kind': kind, 'pattern_id': self.pattern['id'], 'span': self.fact.span(node)}
            if row not in self.unknowns:
                self.unknowns.append(row)

    def evidence(self, node):
        span = self.fact.span(node)
        return (span['path'], span['start_byte'], span['end_byte'])

    def remember(self, value, node):
        if value is not None and value.kind == 'coordinate' and value.steps:
            value = replace(value, evidence=tuple(dict.fromkeys((*value.evidence, self.evidence(node)))))
            key = _path_key(value)
            old = self.found.get(key)
            if old is not None:
                value = replace(value, evidence=tuple(dict.fromkeys((*old.evidence, *value.evidence))))
            self.found[key] = value
        return value

    def scalar(self, node, env):
        if isinstance(node, ast.Name) and node.id in env:
            value = env[node.id]
            return value.constant if value is not None and value.kind == 'constant' else None
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
            value = self.scalar(node.operand, env)
            if type(value) is int:
                return -value if isinstance(node.op, ast.USub) else value
        return self.fact.static(node) if node is not None else None

    def select(self, value, index, node, arity=None):
        if value is None or not (type(index) is int or index == '*'):
            return None
        if value.kind == 'groups':
            if type(index) is not int:
                return None
            if index < 0:
                if arity is None:
                    self.unknown('negative_groups_index_without_arity', node)
                    return None
                index += arity
            return _Value('coordinate', group=index + 1, evidence=(*value.evidence, self.evidence(node)), group_arity=arity)
        if value.kind != 'split':
            return None
        parent = value.parent
        if len(parent.steps) >= self.budget.max_split_depth:
            self.unknown('split_depth_budget', node)
            return None
        step = (value.delimiter, value.maxsplit, index, arity)
        return self.remember(replace(parent, steps=(*parent.steps, step),
                                     evidence=(*value.evidence, self.evidence(node))), node)

    def invalidate(self, value, env):
        if value is not None and value.kind in {'split', 'tuple', 'container'}:
            self.invalid_values[id(value)] = value
            for name, bound in list(env.items()):
                if bound is value:
                    env[name] = None
            if value.kind in {'tuple', 'container'}:
                for nested in value.constant:
                    self.invalidate(nested, env)
        elif value is not None and value.kind == 'deferred':
            for name in value.constant:
                bound = env.get(name)
                if bound is not None and bound.kind in {'split', 'tuple', 'container'}:
                    self.invalidate(bound, env)
                env[name] = None

    def usable(self, value):
        if value is None or id(value) in self.invalid_values:
            return None
        if value.kind in {'tuple', 'container'} and any(v is not None and self.usable(v) is None for v in value.constant):
            return None
        return value

    def contains_anchor(self, node):
        span, use = self.fact.span(node), self.pattern['use_span']
        return span['path'] == use['path'] and span['start_byte'] <= use['start_byte'] <= use['end_byte'] <= span['end_byte']

    def local_region(self, statement, env):
        anchored = self.contains_anchor(statement)
        is_try = isinstance(statement, (ast.Try, getattr(ast, 'TryStar', ast.Try)))
        carried = {name: value for name, value in env.items() if value is not None and value.kind in {'match', 'coordinate'}}
        if not anchored and not (is_try and carried):
            return
        self.unknown('source_match_local_region_control_unresolved', statement)
        self.control_regions.append(self.fact.span(statement))
        local = {name: None for name in env}
        if is_try and not anchored:
            local.update(carried)
        if isinstance(statement, ast.While):
            self.evaluate(statement.test, local)
        bodies = [statement.body, statement.orelse]
        if isinstance(statement, (ast.Try, getattr(ast, 'TryStar', ast.Try))):
            bodies.extend([handler.body for handler in statement.handlers])
            bodies.append(statement.finalbody)
        for body in bodies:
            # The while test may create the fresh match used by its body.
            if (any(self.contains_anchor(s) for s in body) or isinstance(statement, ast.While) and self.contains_anchor(statement.test)
                    or is_try and not anchored and body is statement.body):
                self.block(body, dict(local))

    def source_call(self, node, actuals, env):
        def carries(value):
            return value is not None and (value.kind in {'match', 'coordinate', 'split', 'groups'}
                   or value.kind == 'tuple' and any(carries(v) for v in value.constant))
        tracked = {position: value for position, value in actuals.items()
                   if carries(value)}
        if not tracked:
            return False, None
        call = self.context.get('calls', {}).get(_position(self.fact.span(node)))
        if call is None:
            self.unknown('capture_call_target_unresolved', node)
            return False, None
        targets = {t['function_id'] for t in call.get('targets', []) if t.get('resolved')}
        if len(targets) != 1:
            self.unknown('capture_call_target_unresolved', node)
            return False, None
        fid = next(iter(targets))
        function = self.context.get('functions', {}).get(fid)
        if function is None or len(self.stack) >= self.budget.max_call_depth or fid in self.stack:
            self.unknown('capture_call_depth_or_recursion_budget', node)
            return False, None
        if not self.callee_binding(node.func, function):
            self.unknown('capture_call_target_unresolved', node)
            return False, None
        fact = self.fact.registry.get(function['span']['path'])
        target = fact.nodes.get((function['span']['start_byte'], function['span']['end_byte'])) if fact else None
        if not isinstance(target, (ast.FunctionDef, ast.AsyncFunctionDef)) or fact.scope_directives[target]:
            self.unknown('capture_call_definition_or_scope_unresolved', node)
            return False, None
        arguments = {a['slot']: a for a in call.get('arguments', []) if not a.get('spread')}
        parameters = {p['index']: p for p in function.get('parameters', [])}
        bound, consumed = {}, set()
        for binding in call.get('argument_bindings', []):
            if binding.get('function_id') != fid or binding.get('binding_status') != 'direct_actual_formal':
                continue
            argument, parameter = arguments.get(binding['slot']), parameters.get(binding['parameter_index'])
            if argument is None or parameter is None:
                continue
            position = _position(argument)
            if position in actuals:
                name = parameter['name']
                if name in bound:
                    self.unknown('capture_call_binding_ambiguous', node)
                    return False, None
                bound[name] = actuals[position]
                consumed.add(position)
        if not set(tracked) <= consumed:
            self.unknown('capture_call_binding_incomplete', node)
            return False, None
        child = _CaptureFlow(fact, self.pattern, self.budget, self.unknowns, self.context, (*self.stack, fid))
        child.remaining = self.remaining
        child.invalid_values = self.invalid_values
        local = {a.arg: None for a in [*target.args.posonlyargs, *target.args.args, *target.args.kwonlyargs]}
        local.update(bound)
        live = child.block(target.body, local)
        self.remaining, self.exhausted = child.remaining, self.exhausted or child.exhausted
        evidence = (self.evidence(node), (fact.source.path, function['span']['start_byte'], function['span']['end_byte']))
        for key, value in child.found.items():
            value = replace(value, evidence=tuple(dict.fromkeys((*value.evidence, *evidence))))
            old = self.found.get(key)
            self.found[key] = replace(value, evidence=tuple(dict.fromkeys((*(old.evidence if old else ()), *value.evidence))))
        self.control_regions.extend(child.control_regions)
        self.call_evidence.append({'call_span': self.fact.span(node), 'function_span': function['span'],
                                   'binding_status': 'direct_actual_formal', 'parameter_names': sorted(bound)})
        self.call_evidence.extend(child.call_evidence)
        returns = [*child.returns, *([None] if live else [])]
        value = returns[0] if returns and all(v == returns[0] for v in returns) else None
        if value is not None:
            value = replace(value, evidence=tuple(dict.fromkeys((*value.evidence, *evidence))))
        return True, value

    def callee_binding(self, expression, function, depth=0):
        """A resolved edge cannot override an explicit local callable shadow."""
        if depth > self.budget.max_call_depth:
            return False
        if isinstance(expression, ast.Attribute):
            return True  # Exact source receiver/import identity is in the edge.
        if not isinstance(expression, ast.Name):
            return False
        name = expression.id
        for scope in self.fact.lexical_scopes(expression):
            if name in self.fact.scope_directives[scope] or '*' in self.fact.imports[scope]:
                return False
            if name in self.fact.imports[scope]:
                return self.fact.import_counts[scope][name] == 1 and not self.fact.writes[scope][name]
            if self.fact.writes[scope][name]:
                definition = self.fact.definition(name, expression)
                if definition is not None:
                    return self.callee_binding(definition, function, depth + 1)
                declarations = [n for n in ast.iter_child_nodes(scope) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name]
                return (len(declarations) == 1 and self.fact.writes[scope][name] == 1
                        and _position(self.fact.span(declarations[0])) == _position(function['span']))
        return False

    def builtin(self, expression, name):
        if not isinstance(expression, ast.Name) or expression.id != name:
            return False
        return not any(self.fact.writes[scope][name] or name in self.fact.imports[scope]
                       or name in self.fact.scope_directives[scope] or '*' in self.fact.imports[scope]
                       for scope in self.fact.lexical_scopes(expression))

    def root_write(self, target, env):
        root = target
        while isinstance(root, (ast.Subscript, ast.Attribute)):
            root = root.value
        if isinstance(root, ast.Name):
            self.invalidate(env.get(root.id), env)

    def evaluate(self, node, env):
        if node is None:
            return None
        self.remaining -= 1
        if self.remaining < 0:
            if not self.exhausted:
                self.unknown('analysis_node_budget', node)
                self.exhausted = True
            return None
        if isinstance(node, ast.Name):
            return self.usable(env.get(node.id))
        if isinstance(node, ast.Constant) and type(node.value) in {str, int}:
            return _Value('constant', constant=node.value)
        if isinstance(node, (ast.UnaryOp, ast.BinOp)):
            static = self.scalar(node, env)
            if type(static) in {str, int}:
                return _Value('constant', constant=static)
        if isinstance(node, ast.NamedExpr):
            value = self.evaluate(node.value, env)
            self.bind(node.target, value, env)
            return value
        if isinstance(node, ast.IfExp):
            self.evaluate(node.test, env)
            left = self.evaluate(node.body, dict(env))
            right = self.evaluate(node.orelse, dict(env))
            for value, fallback in ((left, node.orelse), (right, node.body)):
                empty = (isinstance(fallback, ast.Constant) and fallback.value is None
                         or isinstance(fallback, (ast.List, ast.Tuple)) and not fallback.elts)
                if empty and value is not None and value.kind in {'coordinate', 'split', 'match'}:
                    self.unknown('conditional_capture_value_applicability_unresolved', node)
                    self.control_regions.append(self.fact.span(node))
                    return value
            return left if left is not None and left == right else None
        if isinstance(node, ast.BoolOp) and isinstance(node.op, ast.Or) and len(node.values) == 2:
            left = self.evaluate(node.values[0], env)
            fallback = self.scalar(node.values[1], env)
            if left is not None and left.kind == 'coordinate' and fallback == '':
                # An absent capture has no source byte coordinate and is
                # discarded by evaluate_coordinate; present strings retain it.
                return left
            self.evaluate(node.values[1], env)
            return None
        if isinstance(node, ast.Call):
            if _position(self.fact.span(node)) == _position(self.pattern['use_span']):
                return _Value('match', evidence=(self.evidence(node),))
            receiver = self.evaluate(node.func.value, env) if isinstance(node.func, ast.Attribute) else None
            callee = env.get(node.func.id) if isinstance(node.func, ast.Name) else None
            if isinstance(node.func, ast.Attribute) and receiver is not None:
                if receiver.kind == 'match' and node.func.attr == 'group' and not node.keywords:
                    groups = [self.scalar(arg, env) for arg in node.args]
                    if groups and all(type(group) in {int, str} and (type(group) is str or group > 0) for group in groups):
                        values = tuple(_Value('coordinate', group=group, evidence=(*receiver.evidence, self.evidence(node))) for group in groups)
                        return values[0] if len(values) == 1 else _Value('tuple', constant=values)
                    self.unknown('nonconstant_or_whole_match_group', node)
                elif receiver.kind == 'match' and node.func.attr == 'groups' and not node.args and not node.keywords:
                    return _Value('groups', evidence=(*receiver.evidence, self.evidence(node)))
                elif receiver.kind == 'coordinate' and node.func.attr == 'split':
                    if len(node.args) > 2 or any(k.arg not in {'sep', 'maxsplit'} for k in node.keywords):
                        self.unknown('unsupported_split_arguments', node)
                        return None
                    args = {k.arg: k.value for k in node.keywords}
                    if (node.args and 'sep' in args) or (len(node.args) > 1 and 'maxsplit' in args):
                        self.unknown('duplicate_split_arguments', node)
                        return None
                    delimiter = self.scalar(node.args[0] if node.args else args.get('sep'), env)
                    limit_node = node.args[1] if len(node.args) > 1 else args.get('maxsplit')
                    limit = self.scalar(limit_node, env) if limit_node is not None else -1
                    if type(delimiter) is str and delimiter and type(limit) is int:
                        return _Value('split', parent=receiver, delimiter=delimiter, maxsplit=limit,
                                      evidence=(*receiver.evidence, self.evidence(node)))
                    self.unknown('nonconstant_or_whitespace_split', node)
                    for arg in [*node.args, *(kw.value for kw in node.keywords)]:
                        self.evaluate(arg, env)
                    return None
            # Unknown calls may mutate a tracked split list. Strings are immutable.
            actuals = {_position(self.fact.span(arg)): self.evaluate(arg, env)
                       for arg in [*node.args, *(kw.value for kw in node.keywords)]}
            if self.builtin(node.func, 'len') and len(node.args) == 1 and not node.keywords:
                return None  # A source split list's length never mutates it.
            if self.builtin(node.func, 'map') and len(node.args) == 2 and not node.keywords:
                sequence = actuals.get(_position(self.fact.span(node.args[1])))
                if sequence is not None and sequence.kind == 'split' and any(self.builtin(node.args[0], name) for name in ('int', 'float', 'str', 'bool', 'ord', 'chr')):
                    self.select(sequence, '*', node)
                    self.unknown('raw_split_iteration_mapper_output_not_inferred', node)
                    return None
            handled, result = self.source_call(node, actuals, env)
            if handled:
                return result
            if callee is not None and callee.kind == 'deferred':
                self.unknown('deferred_scope_may_mutate_capture_list', node)
                self.invalidate(callee, env)
            for arg in [*node.args, *(kw.value for kw in node.keywords)]:
                value = actuals.get(_position(self.fact.span(arg)))
                if value is not None and value.kind in {'split', 'tuple', 'container', 'deferred'}:
                    self.unknown('split_list_escapes_to_unknown_call', node)
                    self.invalidate(value, env)
            if receiver is not None and receiver.kind in {'split', 'tuple', 'container'}:
                self.unknown('unsupported_split_list_method', node)
                self.invalidate(receiver, env)
            return None
        if isinstance(node, ast.Subscript):
            parent = self.evaluate(node.value, env)
            index = self.scalar(node.slice, env)
            if parent is not None and parent.kind == 'match':
                if type(index) in {str, int} and (type(index) is str or index > 0):
                    return _Value('coordinate', group=index, evidence=(*parent.evidence, self.evidence(node)))
                self.unknown('nonconstant_or_whole_match_group', node)
                return None
            if parent is not None and parent.kind in {'split', 'groups'}:
                if type(index) is not int:
                    self.unknown('nonconstant_split_index', node)
                    self.evaluate(node.slice, env)
                return self.select(parent, index, node)
            if parent is not None and parent.kind == 'tuple' and type(index) is int and -len(parent.constant) <= index < len(parent.constant):
                return self.usable(parent.constant[index])
            return None
        if isinstance(node, (ast.Tuple, ast.List)):
            return _Value('tuple', constant=tuple(self.evaluate(item, env) for item in node.elts))
        if isinstance(node, ast.Set):
            return _Value('container', constant=tuple(self.evaluate(item, env) for item in node.elts))
        if isinstance(node, ast.Dict):
            return _Value('container', constant=tuple(self.evaluate(item, env) for item in [*node.keys, *node.values]))
        if isinstance(node, ast.Lambda):
            return _Value('deferred', constant=tuple(sorted({n.id for n in ast.walk(node) if isinstance(n, ast.Name)})))
        if isinstance(node, (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)):
            if len(node.generators) == 1 and not node.generators[0].is_async:
                generator = node.generators[0]
                sequence = self.evaluate(generator.iter, env)
                if sequence is not None and sequence.kind == 'split':
                    saved = dict(self.found)
                    coordinate = self.select(sequence, '*', generator.iter)
                    local = dict(env)
                    self.bind(generator.target, coordinate, local)
                    for condition in generator.ifs:
                        self.evaluate(condition, local)
                    expressions = [node.key, node.value] if isinstance(node, ast.DictComp) else [node.elt]
                    for expression in expressions:
                        self.evaluate(expression, local)
                    if self.usable(sequence) is None:
                        self.found = saved
                        self.unknown('split_iteration_may_mutate_input', node)
                    else:
                        self.unknown('raw_split_iteration_filter_or_mapper_output_not_inferred', node)
                    return None
            self.unknown('comprehension_capture_flow_unsupported', node)
            for child in ast.walk(node):
                if isinstance(child, ast.Name):
                    self.invalidate(env.get(child.id), env)
            return None
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.expr):
                self.evaluate(child, env)
        return None

    def bind(self, target, value, env):
        if isinstance(target, ast.Name):
            env[target.id] = value
        elif isinstance(target, (ast.Tuple, ast.List)):
            if any(isinstance(t, ast.Starred) for t in target.elts):
                self.unknown('starred_unpacking_unsupported', target)
                for name in ast.walk(target):
                    if isinstance(name, ast.Name):
                        env[name.id] = None
                return
            for index, child in enumerate(target.elts):
                item = (value.constant[index] if value is not None and value.kind == 'tuple' and len(value.constant) == len(target.elts)
                        else self.select(value, index, child, len(target.elts)))
                self.bind(child, item, env)
        else:
            # Assignment into a split list invalidates every local alias to it.
            self.invalidate(value, env)
            self.root_write(target, env)
            self.unknown('nonlocal_or_container_write', target)

    def block(self, statements, env):
        for statement in statements:
            if self.exhausted:
                break
            if isinstance(statement, (ast.Assign, ast.AnnAssign)):
                value = self.evaluate(statement.value, env)
                for target in statement.targets if isinstance(statement, ast.Assign) else [statement.target]:
                    self.bind(target, value, env)
            elif isinstance(statement, ast.If):
                self.evaluate(statement.test, env)
                left, right = dict(env), dict(env)
                left_live = self.block(statement.body, left)
                right_live = self.block(statement.orelse, right)
                if left_live and right_live:
                    if any(left.get(name) != right.get(name) for name in set(left) | set(right)):
                        self.unknown('ambiguous_branch_binding', statement)
                    env.update({name: left.get(name) if left.get(name) == right.get(name) else None for name in set(left) | set(right)})
                elif left_live or right_live:
                    env.update(left if left_live else right)
                else:
                    return False
            elif isinstance(statement, (ast.With, ast.AsyncWith)):
                for item in statement.items:
                    self.evaluate(item.context_expr, env)
                    if item.optional_vars:
                        self.bind(item.optional_vars, None, env)
                if not self.block(statement.body, env):
                    return False
            elif isinstance(statement, (ast.Return, ast.Raise)):
                result = self.evaluate(statement.value if isinstance(statement, ast.Return) else statement.exc, env)
                if isinstance(statement, ast.Return):
                    self.returns.append(result)
                return False
            elif isinstance(statement, (ast.Break, ast.Continue)):
                return False
            elif isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                for decorator in statement.decorator_list:
                    self.evaluate(decorator, env)
                if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    for default in [*statement.args.defaults, *statement.args.kw_defaults]:
                        self.evaluate(default, env)
                env[statement.name] = _Value('deferred', constant=tuple(sorted({n.id for n in ast.walk(statement) if isinstance(n, ast.Name)})))
            elif isinstance(statement, (ast.For, ast.AsyncFor, ast.While, ast.Try, getattr(ast, 'TryStar', ast.Try), ast.Match, ast.AugAssign, ast.Delete)):
                self.unknown('loop_exception_or_mutation_flow_unsupported', statement)
                if isinstance(statement, (ast.For, ast.AsyncFor, ast.While, ast.Try, getattr(ast, 'TryStar', ast.Try))):
                    self.local_region(statement, env)
                for node in ast.walk(statement):
                    if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
                        self.invalidate(env.get(node.id), env)
                        env[node.id] = None
                    elif isinstance(node, (ast.Subscript, ast.Attribute)) and isinstance(node.ctx, (ast.Store, ast.Del)):
                        self.root_write(node, env)
                    elif isinstance(node, ast.Call):
                        # A skipped control-flow region can mutate an existing
                        # list through a call, including a nested carrier.
                        for child in ast.walk(node):
                            if isinstance(child, ast.Name):
                                self.invalidate(env.get(child.id), env)
            elif isinstance(statement, (ast.Import, ast.ImportFrom)):
                for alias in statement.names:
                    env[alias.asname or alias.name.split('.')[0]] = None
            else:
                for child in ast.iter_child_nodes(statement):
                    if isinstance(child, ast.expr):
                        self.evaluate(child, env)
        return True

    def run(self):
        use = self.fact.nodes.get((self.pattern['use_span']['start_byte'], self.pattern['use_span']['end_byte']))
        function = self.fact.scope(use)
        if not isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return []
        if self.fact.scope_directives[function]:
            self.unknown('global_or_nonlocal_capture_bindings', function)
            return []
        self.block(function.body, {a.arg: None for a in [*function.args.posonlyargs, *function.args.args, *function.args.kwonlyargs]})
        values = list(self.found.values())
        # Refine a field when the parser itself derives smaller fields from it.
        leaves = [v for v in values if not any(v.group == child.group and len(v.steps) < len(child.steps)
                    and _semantic_path(child)[:len(v.steps)] == _semantic_path(v) for child in values)]
        result = []
        for value in sorted(leaves, key=lambda v: repr(_path_key(v)))[:self.budget.max_coordinates]:
            steps = [{'delimiter': d, 'maxsplit': m, 'index': i, 'arity': a} for d, m, i, a in value.steps]
            result.append({'id': stable_id('parsed-field', self.pattern['id'], _path_key(value)),
                           'pattern_id': self.pattern['id'], 'group': value.group, 'group_arity': value.group_arity,
                           'steps': steps, 'source_spans': [{'path': p, 'start_byte': a, 'end_byte': b} for p, a, b in value.evidence],
                           'binding_status': 'source_local_capture_split_flow',
                           'control_regions': self.control_regions,
                           'source_call_bindings': self.call_evidence,
                           'control_flow_status': 'local_match_region_runtime_unresolved' if self.control_regions else 'source_local_flow'})
        return result


def _split_spans(value, delimiter, maxsplit):
    try:
        parts = value.split(delimiter, maxsplit)
    except (ValueError, OverflowError):
        return None
    result, start = [], 0
    for part in parts:
        result.append((start, start + len(part)))
        start += len(part) + len(delimiter)
    return result


def evaluate_coordinate(coordinate, match, names):
    """Evaluate only closed string split/index operations, returning input offsets."""
    if match is None:
        return None
    group = names.get(coordinate['group']) if type(coordinate['group']) is str else coordinate['group']
    if type(group) is not int or not 1 <= group <= len(match['groups']):
        return None
    if coordinate.get('group_arity') is not None and coordinate['group_arity'] != len(match['groups']):
        return None
    value = match['groups'][group - 1]
    if value is None:
        return None
    start, end = match['spans'][group - 1]
    shape = []
    for step in coordinate['steps']:
        spans = _split_spans(value, step['delimiter'], step['maxsplit'])
        if spans is None:
            return None
        if step.get('arity') is not None and len(spans) != step['arity']:
            return None
        if type(step['index']) is not int:
            return None  # Iteration templates are instantiated before transport.
        index = step['index'] if step['index'] >= 0 else len(spans) + step['index']
        if not 0 <= index < len(spans):
            return None
        a, b = spans[index]
        shape.append([len(spans), index])
        value, start, end = value[a:b], start + a, start + b
    return {'group': group, 'value': value, 'span': [start, end], 'shape': shape}


def expand_coordinates(fields, match, names, limit):
    """Bind source iteration ordinals to a finite matched input, within budget."""
    output = []
    for field in fields:
        pending = [field]
        while pending and len(output) < limit:
            current = pending.pop(0)
            index = next((i for i, step in enumerate(current['steps']) if step['index'] == '*'), None)
            if index is None:
                output.append(current)
                continue
            parent = evaluate_coordinate(dict(current, steps=current['steps'][:index]), match, names)
            if parent is None:
                continue
            step = current['steps'][index]
            spans = _split_spans(parent['value'], step['delimiter'], step['maxsplit'])
            if spans is None:
                continue
            for ordinal in range(min(len(spans), limit - len(output) - len(pending))):
                steps = [dict(s) for s in current['steps']]
                steps[index]['index'] = ordinal
                pending.append(dict(current, id=stable_id('parsed-field-ordinal', field['id'], steps), steps=steps,
                                    template_id=field['id'], iteration_status='source_split_ordinal_mapper_and_filter_semantics_unknown'))
        if len(output) >= limit:
            break
    def path(field):
        return tuple((s['delimiter'], s['maxsplit'], s['index']) for s in field['steps'])
    return [field for field in output if not any(field['group'] == child['group'] and len(field['steps']) < len(child['steps'])
            and path(child)[:len(field['steps'])] == path(field) for child in output)]


def _validation_group(selected, match, ancestors):
    """Nested regex wrappers may be ancestors of the same parsed leaf."""
    group = selected['group']
    a, b = selected['span']
    choices = [i for i, (start, end) in enumerate(match['spans'], 1)
               if start >= 0 and start <= a <= b <= end and (i == group or group in ancestors.get(str(i), []))]
    return max(choices, key=lambda i: len(ancestors.get(str(i), [])), default=group)


def _prepared(corpus, frontend, budget):
    facts, sources, unknowns, skipped = {}, {}, [], Counter()
    for path, metadata in corpus['sources'].items():
        if metadata.get('language', corpus['language']) != 'python' or metadata.get('parse_error') or not metadata.get('complete_file', True):
            continue
        source = Source(path, metadata['code'], 'python')
        try:
            facts[path] = _SourceFacts(source, frontend.get('functions', []))
        except (SyntaxError, ValueError):
            continue
        sources[path] = source
    for fact in facts.values():
        fact.registry = facts
    patterns = _patterns(facts, budget, skipped)
    context = {'calls': {_position(call): call for call in frontend.get('production_calls', [])},
               'functions': {f['id']: f for f in frontend.get('functions', [])}}
    coordinates = [coordinate for pattern in patterns
                   for coordinate in _CaptureFlow(facts[pattern['use_span']['path']], pattern, budget, unknowns, context).run()]
    return sources, facts, patterns, coordinates, unknowns, skipped


def extract_parsed_coordinates(corpus, frontend, *, budget=None):
    """Return compact source capture/split paths without enumerating candidates."""
    budget = budget or ParsedFieldBudget()
    _, _, patterns, coordinates, unknowns, skipped = _prepared(corpus, frontend, budget)
    return {'patterns': patterns, 'coordinates': coordinates, 'unknowns': unknowns, 'skipped': dict(skipped)}


def generate_parsed_field_cells(corpus, frontend, *, budget=None):
    budget = budget or ParsedFieldBudget()
    sources, facts, patterns, coordinates, unknowns, skipped = _prepared(corpus, frontend, budget)
    enriched = _finite(corpus) if sources else corpus
    tests, capsules, groups = corpus['tests'], defaultdict(list), defaultdict(list)
    for capsule in corpus.get('capsules', []):
        capsules[capsule['test_id']].append(capsule)
    for donor in enriched['donors']:
        if (donor.get('kind') == 'parameter_row' or donor['test_id'] not in tests or donor['span']['path'] not in sources
                or not capsules[donor['test_id']] or donor.get('oracle_dependency') or donor.get('diagnostic')
                or not donor.get('literal_known') or type(donor.get('literal_value')) is not str):
            continue
        if len(donor['literal_value'].encode()) > budget.max_input_bytes or source_text(corpus, donor['span']) != donor['text']:
            continue
        for port in carrier_ports(sources[donor['span']['path']], donor, frontend):
            if not port.get('structural_path'):
                groups[structural_slot_key(port)].append((donor, port))
    call_map = {_position(c): c for c in frontend.get('calls', [])}
    context = {'calls': call_map, 'functions': {f['id']: f for f in frontend.get('functions', [])},
               'forwarding': defaultdict(list), 'reachable': {}}
    for call in frontend.get('production_calls', []):
        context['forwarding'][call['function_id']].extend(t['function_id'] for t in call.get('targets', []))
    pool, attempts, matched_slots = {}, 0, 0
    for pattern in patterns:
        fields = [c for c in coordinates if c['pattern_id'] == pattern['id']]
        if not fields:
            continue
        exact = _flow(pattern, frontend, facts, budget)
        for key, available in sorted(groups.items(), key=lambda item: repr(item[0])):
            members = []
            for donor, port in available:
                proof = exact.get((_position(port['call_span']), port['argument_slot']))
                other_slot_proved = any(position == _position(port['call_span']) for position, _ in exact)
                if proof is not None or not other_slot_proved and budget.allow_proximity and _proximity(pattern, port, context, budget):
                    members.append((donor, port, proof))
            members.sort(key=lambda row: (row[2] is None, tests[row[0]['test_id']].get('retrieval_rank') or 10**9, _position(row[0]), row[0]['id']))
            members = members[:budget.max_inputs_per_slot]
            if len({d['literal_value'] for d, _, _ in members}) < 2:
                continue
            matches = _match(pattern, [d['literal_value'] for d, _, _ in members], budget, skipped)
            if matches is None:
                continue
            matched = [(entry, match) for entry, match in zip(members, matches['matches']) if match is not None]
            if len({entry[0]['literal_value'] for entry, _ in matched}) < 2:
                continue
            matched_slots += 1
            proposals, proposed = [], set()
            for (target, port, proof), before in matched:
                row_edits, instantiation = _row_edits(corpus, target, facts)
                if row_edits is None:
                    skipped['complete_row_instantiation_unavailable'] += 1
                    continue
                observation_ids = call_map.get(_position(port['call_span']), {}).get('observation_ids', [])
                target_fields = expand_coordinates(fields, before, matches['names'], budget.max_coordinates)
                evaluated = {field['id']: evaluate_coordinate(field, before, matches['names']) for field in target_fields}
                for field in target_fields:
                    selected = evaluated[field['id']]
                    if selected is None:
                        continue
                    a, b = selected['span']
                    if any(other is not None and other['span'] != [a, b] and max(a, other['span'][0]) < min(b, other['span'][1])
                           for other in evaluated.values()):
                        skipped['overlapping_parser_coordinates'] += 1
                        continue
                    for (origin, _, _), other_match in matched:
                        other = evaluate_coordinate(field, other_match, matches['names'])
                        if other is None or other['value'] == selected['value']:
                            continue
                        replacement = other['value']
                        value = target['literal_value'][:a] + replacement + target['literal_value'][b:]
                        if len(value.encode()) > budget.max_input_bytes:
                            continue
                        if proof is not None and observation_ids and any(d['test_id'] == target['test_id'] and d.get('parameter_row') == target.get('parameter_row')
                                and d['literal_value'] == value and call_map.get(_position(p['call_span']), {}).get('observation_ids') == observation_ids
                                for (d, p, _), _ in matched):
                            skipped['already_observed_same_q_input'] += 1
                            continue
                        after = repr(value) if target.get('finite_input') else format_source_string(value, 'python', target['text'])
                        if after is None:
                            continue
                        edit = {'span': target['span'], 'before': target['text'], 'after': after}
                        edits = [edit, *row_edits]
                        identifier = stable_id('parsed-field-cell', target['test_id'], edits)
                        if identifier in pool or identifier in proposed:
                            continue
                        proposals.append((identifier, value, target, origin, proof, before, field, selected, evaluated, replacement, edits, instantiation, observation_ids, target_fields))
                        proposed.add(identifier)
                        attempts += 1
                        if attempts >= budget.max_attempts:
                            break
                    if attempts >= budget.max_attempts:
                        break
                if attempts >= budget.max_attempts:
                    break
            checked = _match(pattern, [p[1] for p in proposals], budget, skipped) if proposals else None
            if checked is not None:
                for proposal, after_match in zip(proposals, checked['matches']):
                    identifier, value, target, origin, proof, before, field, selected, evaluated, replacement, edits, instantiation, observation_ids, target_fields = proposal
                    a, b = selected['span']
                    group = selected['group']
                    validation_group = _validation_group(selected, before, matches['ancestors'])
                    group_start, group_end = before['spans'][validation_group - 1]
                    group_replacement = target['literal_value'][group_start:a] + replacement + target['literal_value'][b:group_end]
                    if not _same_other_coordinates(before, after_match, validation_group, group_replacement, matches['ancestors']):
                        skipped['regex_rematch_changed_other_coordinate_or_invalid'] += 1
                        continue
                    after_selected = evaluate_coordinate(field, after_match, matches['names'])
                    if (after_selected is None or after_selected['value'] != replacement or after_selected['shape'] != selected['shape']
                            or after_selected['span'] != [a, a + len(replacement)]):
                        skipped['split_structure_changed'] += 1
                        continue
                    delta = len(replacement) - (b - a)
                    valid = True
                    for neighbor in target_fields:
                        old = evaluated[neighbor['id']]
                        new = evaluate_coordinate(neighbor, after_match, matches['names'])
                        if old is None:
                            valid = new is None
                        elif old['span'] == [a, b]:
                            valid = new is not None and new['value'] == replacement and new['shape'] == old['shape']
                        else:
                            x, y = old['span']
                            expected_span = [x, y] if y <= a else [x + delta, y + delta]
                            valid = new is not None and new['value'] == old['value'] and new['shape'] == old['shape'] and new['span'] == expected_span
                        if not valid:
                            break
                    if not valid:
                        skipped['other_parser_coordinate_changed'] += 1
                        continue
                    evidence = [pattern['pattern_span'], pattern['declaration_span'], pattern['use_span'], *field['source_spans'], target['span'], origin['span'], *(proof or [])]
                    pool[identifier] = {'id': identifier, 'kind': 'source_parsed_field_coordinate', 'base_test_id': target['test_id'],
                        'focus_test_id': target['test_id'], 'source_test_ids': sorted({target['test_id'], origin['test_id']}), 'language': 'python', 'edits': edits, 'imports': [],
                        'relation': {'domain': 'source_parsed_field', 'pattern_id': pattern['id'], 'coordinate_id': field['id'],
                                     'group': group, 'regex_validation_group': validation_group, 'steps': field['steps'], 'before': selected['value'], 'after': replacement,
                                     'capture_coordinate': {'unicode_span': [a, b], 'utf8_span': [len(target['literal_value'][:a].encode()), len(target['literal_value'][:b].encode())]},
                                     'input_slot': list(key), 'source_observation_ids': observation_ids,
                                     'binding_status': 'source_actual_formal_flow' if proof is not None else 'source_owner_proximity_unresolved',
                                     'binding_path': proof or [], 'rematch': 'only_selected_parser_leaf_and_ancestor_captures_changed',
                                     'parameter_instantiation': instantiation, 'status': 'source_grammar_hypothesis_runtime_unconfirmed'},
                        'oracle': {'mode': 'retain_all', 'source_test_id': target['test_id'], 'assertion_ids': [c['id'] for c in capsules[target['test_id']]],
                                   'applicability': 'requires_independent_admission'},
                        'provenance': {'source_spans': evidence, 'target_span': target['span'], 'source_donor_ids': [target['id'], origin['id']],
                                       'pattern': pattern, 'coordinate': field, 'source_input': target['literal_value'], 'source_coordinate_input': origin['literal_value']},
                        'selection': {'proof_order': 0 if proof is not None else 1, 'focus_order': tests[target['test_id']].get('retrieval_rank') or 10**9,
                                      'edit_size': sum(max(len(e['before'].encode()), len(e['after'].encode())) for e in edits)}}
            if attempts >= budget.max_attempts:
                break
        if attempts >= budget.max_attempts:
            break
    queues = defaultdict(deque)
    for candidate in sorted(pool.values(), key=lambda c: (c['selection']['proof_order'], c['selection']['focus_order'], c['base_test_id'], c['id'])):
        queues[candidate['base_test_id']].append(candidate)
    candidates = []
    while queues and len(candidates) < budget.max_candidates:
        for test_id in list(queues):
            candidates.append(queues[test_id].popleft())
            if not queues[test_id]:
                del queues[test_id]
            if len(candidates) >= budget.max_candidates:
                break
    return {'candidates': candidates, 'patterns': patterns, 'coordinates': coordinates, 'unknowns': unknowns, 'budget': asdict(budget),
            'counts': {'patterns': len(patterns), 'coordinates': len(coordinates), 'matched_pattern_slots': matched_slots,
                       'pool': len(pool), 'candidates': len(candidates), 'attempts': attempts,
                       'attempt_budget_exhausted': attempts >= budget.max_attempts, 'skipped': dict(skipped)},
            'finite_inputs': enriched.get('finite_inputs', {})}
