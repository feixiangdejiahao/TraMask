"""Local Python prototype: assertion reads -> bound class fields -> writer paths.

No subject code is imported or executed. Paths are syntactic possibilities, not
proofs that a write executes, that a generator is exhausted, or that an oracle
is correct. Unsupported binding is explicit; equal field names never bind
objects from unrelated classes.
"""
from __future__ import annotations

import argparse
import ast
from dataclasses import dataclass, field
import hashlib
import json
from pathlib import Path


def _module_name(path):
    parts = Path(path).with_suffix('').parts
    if parts and parts[0] == 'src':
        parts = parts[1:]
    return '.'.join(parts[:-1] if parts[-1] == '__init__' else parts)


def _walk(node):
    """Visit this lexical function, excluding nested function/class bodies."""
    yield node
    for child in ast.iter_child_nodes(node):
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
            continue
        yield from _walk(child)


@dataclass
class Module:
    path: str
    code: str
    tree: ast.Module
    byte_offsets: list[int] = field(init=False)
    code_bytes: bytes = field(init=False)

    def __post_init__(self):
        self.code_bytes = self.code.encode()
        self.byte_offsets = [0]
        for line in self.code.splitlines(keepends=True):
            self.byte_offsets.append(self.byte_offsets[-1] + len(line.encode()))

    def span(self, node):
        return dict(path=self.path, line=node.lineno, end_line=node.end_lineno,
                    start_byte=self.byte_offsets[node.lineno-1]+node.col_offset,
                    end_byte=self.byte_offsets[node.end_lineno-1]+node.end_col_offset)

    def text(self, node):
        span = self.span(node)
        return self.code_bytes[span['start_byte']:span['end_byte']].decode()


class Index:
    def __init__(self, sources):
        self.modules, self.paths, self.classes, self.parse_errors = {}, {}, {}, []
        for path, value in sorted(sources.items()):
            code = value['code'] if isinstance(value, dict) else value
            if not path.endswith('.py'):
                continue
            try:
                module = Module(path, code, ast.parse(code, filename=path))
            except SyntaxError:
                self.parse_errors.append(path)
                continue
            name = _module_name(path)
            if name in self.modules:
                raise ValueError('Ambiguous module name: '+name)
            self.modules[name], self.paths[path] = module, module
            for node in module.tree.body:
                if isinstance(node, ast.ClassDef):
                    self.classes[name+'.'+node.name] = (module, node)

    def imports(self, module, statements):
        result, stars = {}, []
        name = _module_name(module.path)
        package = name if Path(module.path).name == '__init__.py' else name.rpartition('.')[0]
        for node in statements:
            if isinstance(node, ast.Import):
                for alias in node.names:
                    result[alias.asname or alias.name.split('.')[0]] = alias.name if alias.asname else alias.name.split('.')[0]
            elif isinstance(node, ast.ImportFrom):
                if node.level:
                    parts = package.split('.') if package else []
                    keep = len(parts)-(node.level-1)
                    origin = '.'.join([*parts[:max(keep, 0)], *([node.module] if node.module else [])])
                else:
                    origin = node.module or ''
                for alias in node.names:
                    if alias.name == '*':
                        stars.append(origin)
                    else:
                        result[alias.asname or alias.name] = origin+'.'+alias.name
        return result, stars

    def resolve_symbol(self, symbol, seen=()):
        if symbol in self.classes:
            owner, cls = self.classes[symbol]
            for node in owner.tree.body:
                targets = node.targets if isinstance(node, ast.Assign) else [node.target] if isinstance(node, (ast.AnnAssign, ast.AugAssign)) else []
                if any(isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store) and n.id == cls.name for target in targets for n in ast.walk(target)):
                    return set()
            return {symbol}
        if symbol in seen or len(seen) > 12 or '.' not in symbol:
            return set()
        owner, name = symbol.rsplit('.', 1)
        module = self.modules.get(owner)
        if not module:
            return set()
        bindings, stars = self.imports(module, module.tree.body)
        if name in bindings:
            return self.resolve_symbol(bindings[name], (*seen, symbol))
        matches = set()
        for star in stars:
            if self.star_exports(star, name):
                matches.update(self.resolve_symbol(star+'.'+name, (*seen, symbol)))
        return matches

    def star_exports(self, owner, name):
        module = self.modules.get(owner)
        if not module:
            return False
        exports = [n.value for n in module.tree.body if isinstance(n, ast.Assign)
                   and any(isinstance(t, ast.Name) and t.id == '__all__' for t in n.targets)]
        if exports:
            try:
                names = ast.literal_eval(exports[-1])
            except (ValueError, TypeError):
                return False
            return isinstance(names, (list, tuple)) and name in names
        return not name.startswith('_')

    def resolve_class(self, module, function, expression, before):
        parts = []
        node = expression
        while isinstance(node, ast.Attribute):
            parts.append(node.attr)
            node = node.value
        if not isinstance(node, ast.Name):
            return None, 'non_symbol_constructor'
        parameters = [*function.args.posonlyargs, *function.args.args, *function.args.kwonlyargs]
        parameters += [arg for arg in (function.args.vararg, function.args.kwarg) if arg is not None]
        if any(arg.arg == node.id for arg in parameters):
            return None, 'constructor_symbol_shadowed_by_parameter'
        # Local factories and constructor aliases are outside this prototype.
        # Never fall back to an imported class when the same symbol was assigned.
        for scope in [module.tree, function]:
            for statement in scope.body:
                if scope is function and statement.lineno >= before:
                    continue
                if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    if statement.name == node.id and (scope is function or not isinstance(statement, ast.ClassDef)):
                        return None, 'constructor_symbol_shadowed_by_definition'
                    continue
                if any(isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store) and n.id == node.id for n in _walk(statement)):
                    return None, 'constructor_symbol_shadowed_by_assignment'
        local = [n for n in function.body if isinstance(n, (ast.Import, ast.ImportFrom)) and n.lineno < before]
        bindings, stars = self.imports(module, [*module.tree.body, *local])
        head = bindings.get(node.id, _module_name(module.path)+'.'+node.id)
        symbols = self.resolve_symbol('.'.join([head, *reversed(parts)]))
        if not symbols and not parts and node.id not in bindings:
            for star in stars:
                if self.star_exports(star, node.id):
                    symbols.update(self.resolve_symbol(star+'.'+node.id))
        if len(symbols) != 1:
            return None, 'unresolved_constructor' if not symbols else 'ambiguous_constructor'
        return next(iter(symbols)), None

    def bind_object(self, module, function, name, before, seen=()):
        if name in seen:
            return None, 'cyclic_local_alias'
        assignments = []
        for statement in function.body:
            if statement.lineno >= before:
                break
            if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                if statement.name == name:
                    return None, 'receiver_shadowed_by_definition'
                continue
            written = any(isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store) and n.id == name for n in _walk(statement))
            found = False
            for node in _walk(statement):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target] if isinstance(node, (ast.AnnAssign, ast.AugAssign, ast.NamedExpr)) else []
                if any(isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store) and n.id == name for t in targets for n in ast.walk(t)):
                    found = True
                    if node is not statement:
                        return None, 'conditional_local_binding'
                    if not all(isinstance(t, ast.Name) for t in targets):
                        return None, 'destructured_receiver_binding'
                    assignments.append(node)
            if written and not found:
                return None, 'unsupported_receiver_binding_write'
        if not assignments:
            return None, 'receiver_has_no_local_constructor'
        binding = assignments[-1]
        value = binding.value
        if isinstance(binding, ast.AugAssign):
            return None, 'mutated_receiver_binding'
        if isinstance(value, ast.Name):
            return self.bind_object(module, function, value.id, binding.lineno, (*seen, name))
        if not isinstance(value, ast.Call):
            return None, 'receiver_not_constructor_or_local_alias'
        cls, error = self.resolve_class(module, function, value.func, binding.lineno)
        if error:
            return None, error
        span = module.span(value)
        identifier = hashlib.sha256(json.dumps(span, sort_keys=True).encode()).hexdigest()[:20]
        return dict(class_id=cls, allocation_span=span, object_binding=identifier), None


def _methods(node):
    return {n.name: n for n in node.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}


def _self_name(method):
    positional = [*method.args.posonlyargs, *method.args.args]
    if not positional or any(isinstance(d, ast.Name) and d.id in {'staticmethod', 'classmethod'} for d in method.decorator_list):
        return None
    receiver = positional[0].arg
    if any(isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store) and n.id == receiver for n in _walk(method)):
        return None
    return receiver


def _contexts(module, function, node):
    parents = {child: parent for parent in _walk(function) for child in ast.iter_child_nodes(parent)}
    context, child = [], node
    while child in parents and parents[child] is not function:
        parent = parents[child]
        if isinstance(parent, (ast.If, ast.For, ast.AsyncFor, ast.While, ast.With, ast.AsyncWith, ast.Try, ast.ExceptHandler)):
            branch = next((field for field, value in ast.iter_fields(parent) if isinstance(value, list) and child in value), None)
            context.append(dict(kind=type(parent).__name__, branch=branch, span=module.span(parent)))
        child = parent
    return list(reversed(context))


def _direct_property_field(method, name):
    body = [n for n in method.body if not (isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant) and isinstance(n.value.value, str))]
    if len(body) == 1 and isinstance(body[0], ast.Return):
        value = body[0].value
        if isinstance(value, ast.Attribute) and isinstance(value.value, ast.Name) and value.value.id == name:
            return value.attr
    return None


def _storage_field(module, cls, field):
    methods, aliases, seen = _methods(cls), [], set()
    while field in methods:
        if sum(isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == field for n in cls.body) != 1:
            return None, aliases, 'multiple_descriptor_definitions'
        if field in seen:
            return None, aliases, 'cyclic_property_alias'
        seen.add(field)
        method = methods[field]
        if not any(isinstance(d, ast.Name) and d.id == 'property' for d in method.decorator_list):
            return None, aliases, 'attribute_is_method_or_unknown_descriptor'
        target = _direct_property_field(method, _self_name(method))
        if target is None:
            return None, aliases, 'property_not_direct_field_alias'
        aliases.append(dict(attribute=field, storage_attribute=target, span=module.span(method)))
        field = target
    for node in cls.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == field for t in node.targets):
            if not isinstance(node.value, ast.Constant):
                return None, aliases, 'class_attribute_descriptor_unresolved'
    return field, aliases, None


def _field_writers(module, cls, field):
    rows = []
    for method in _methods(cls).values():
        receiver = _self_name(method)
        if not receiver:
            continue
        for node in _walk(method):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target] if isinstance(node, (ast.AnnAssign, ast.AugAssign)) else []
            for target in targets:
                if isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name) and target.value.id == receiver and target.attr == field:
                    rows.append(dict(method=method.name, span=module.span(node), target_span=module.span(target),
                                     value=module.text(node.value), kind=type(node).__name__,
                                     contexts=_contexts(module, method, node)))
    return sorted(rows, key=lambda row: (row['span']['start_byte'], row['method']))


def _is_generator(method):
    return any(isinstance(n, (ast.Yield, ast.YieldFrom)) for n in _walk(method))


def _bypass_sites(module, method, target):
    """Possible exits before this write/call, not proof they reach test q."""
    contexts = _contexts(module, method, target)
    protected = [row['span'] for row in contexts if row['kind'] == 'Try' and row['branch'] == 'finalbody']
    rows = []
    for node in _walk(method):
        if not hasattr(node, 'lineno') or (node.lineno, node.col_offset) >= (target.lineno, target.col_offset):
            continue
        kind = 'generator_suspension_or_abandonment' if isinstance(node, (ast.Yield, ast.YieldFrom)) else 'explicit_raise' if isinstance(node, ast.Raise) else 'call_may_raise' if isinstance(node, ast.Call) else None
        if kind is None:
            continue
        span = module.span(node)
        # A finally target is not bypassed by an exception from its protected
        # try body. We do not infer suppression of exceptions in nested calls.
        if any(p['start_byte'] <= span['start_byte'] < p['end_byte'] for p in protected):
            continue
        rows.append(dict(kind=kind, span=span, expression=module.text(node),
                         exit='method_exception_or_unresumed_generator', certainty='may'))
    return rows


def _self_calls(module, method, methods):
    receiver = _self_name(method)
    if not receiver:
        return []
    rows = []
    for node in _walk(method):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name) and node.func.value.id == receiver and node.func.attr in methods:
            target = methods[node.func.attr]
            rows.append((node.func.attr, node, dict(caller=method.name, callee=node.func.attr,
                span=module.span(node), contexts=_contexts(module, method, node),
                callee_is_generator=_is_generator(target),
                activation='generator_creation_not_completion' if _is_generator(target) else 'ordinary_call',
                possible_bypass_sites=_bypass_sites(module, method, node))))
    return rows


def _paths(module, cls, roots, writers, max_depth):
    methods = _methods(cls)
    writer_methods = {row['method'] for row in writers}
    result, truncated = [], False
    def visit(root, name, path, seen):
        nonlocal truncated
        if len(result) >= 64 or len(path) > max_depth:
            truncated = True
            return
        if name in writer_methods:
            result.append(dict(root=root, writer_method=name, calls=path,
                               status='syntactic_path_not_execution_proof',
                               requires_generator_runtime_binding=any(edge['callee_is_generator'] for edge in path)
                                   or bool(root.get('callee_is_generator'))))
        if name not in methods:
            return
        for child, node, edge in _self_calls(module, methods[name], methods):
            if child in seen:
                continue
            visit(root, child, [*path, edge], (*seen, child))
    for root in roots:
        visit(root, root['method'], [], (root['method'],))
    return result, truncated


def analyze_assertion(sources, test_path, assertion_line, max_depth=12, *, index=None,
                      assertion_start_byte=None, include_source_hashes=True):
    """Analyze one original assertion, keeping spans in original source bytes."""
    index = index if index is not None else Index(sources)
    module = index.paths.get(test_path)
    if not module:
        return dict(status='unsupported', reason='test_source_missing_or_unparseable', reads=[])
    assertions = [node for node in ast.walk(module.tree) if isinstance(node, ast.Assert) and node.lineno == assertion_line]
    if assertion_start_byte is not None:
        assertions = [node for node in assertions if module.span(node)['start_byte'] == assertion_start_byte]
    if len(assertions) != 1:
        return dict(status='unsupported', reason='assertion_line_not_unique', reads=[])
    assertion = assertions[0]
    functions = [node for node in ast.walk(module.tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.lineno <= assertion.lineno <= node.end_lineno]
    if not functions:
        return dict(status='unsupported', reason='assertion_outside_function', reads=[])
    function = min(functions, key=lambda node: node.end_lineno-node.lineno)
    rows = []
    for read in ast.walk(assertion.test):
        if not isinstance(read, ast.Attribute) or not isinstance(read.ctx, ast.Load):
            continue
        row = dict(read_span=module.span(read), expression=module.text(read), observed_field=read.attr)
        rows.append(row)
        if not isinstance(read.value, ast.Name):
            row.update(status='unsupported', reason='nonlocal_or_nested_receiver')
            continue
        binding, error = index.bind_object(module, function, read.value.id, assertion.lineno)
        if error:
            row.update(status='unsupported', reason=error)
            continue
        owner, cls = index.classes[binding['class_id']]
        if any(keyword.arg == 'metaclass' for keyword in cls.keywords) or '__new__' in _methods(cls):
            row.update(status='unsupported', reason='custom_constructor_type_unresolved', binding=binding)
            continue
        field, aliases, error = _storage_field(owner, cls, read.attr)
        row.update(binding=binding, class_span=owner.span(cls), property_aliases=aliases)
        if error:
            row.update(status='unsupported', reason=error)
            continue
        writers = _field_writers(owner, cls, field)
        row.update(storage_field=field, writers=writers)
        if not writers:
            row.update(status='unsupported', reason='no_direct_writer_in_bound_class')
            continue
        methods = _methods(cls)
        roots = [dict(kind='construction', method='__init__', span=binding['allocation_span'], callee_is_generator=False)]
        for call in _walk(function):
            if not isinstance(call, ast.Call) or call.lineno >= assertion.lineno or not isinstance(call.func, ast.Attribute) or not isinstance(call.func.value, ast.Name):
                continue
            other, issue = index.bind_object(module, function, call.func.value.id, call.lineno)
            if issue or other['object_binding'] != binding['object_binding'] or call.func.attr not in methods:
                continue
            roots.append(dict(kind='test_operation', method=call.func.attr, span=module.span(call),
                              callee_is_generator=_is_generator(methods[call.func.attr])))
        paths, truncated = _paths(owner, cls, roots, writers, max_depth)
        unknown = ['possible_call_exceptions_not_proven_feasible', 'runtime_last_writer_unmeasured',
                   'dynamic_dispatch_and_external_mutation_not_modeled']
        if cls.bases:
            unknown.append('inherited_attribute_dispatch_not_modeled')
        if any(path['requires_generator_runtime_binding'] for path in paths):
            unknown.append('generator_creation_resume_and_exhaustion_not_resolved')
        if truncated:
            unknown.append('call_path_budget_exhausted')
        row.update(status='statically_bound_partial_slice', operation_roots=roots,
                   writer_paths=paths, unknown=unknown)
    return dict(version=1, status='partial' if any(row['status']=='statically_bound_partial_slice' for row in rows) else 'unsupported',
                assertion_span=module.span(assertion), assertion=module.text(assertion),
                test_function=function.name, reads=rows,
                unsupported_reason=None if rows else 'no_attribute_read_in_assertion',
                source_sha256={path: hashlib.sha256(item.code_bytes).hexdigest() for path, item in sorted(index.paths.items())} if include_source_hashes else None,
                parse_errors=index.parse_errors,
                guarantee='source_binding_and_syntactic_paths_only_not_reaching_definition_or_oracle_proof')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('--corpus', required=True, type=Path)
    parser.add_argument('--test-path', required=True)
    parser.add_argument('--line', required=True, type=int)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    corpus = json.loads(args.corpus.read_text())
    result = analyze_assertion(corpus['sources'], args.test_path, args.line)
    result['input_corpus'] = dict(path=str(args.corpus.resolve()), sha256=hashlib.sha256(args.corpus.read_bytes()).hexdigest())
    result['analyzer_sha256'] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    if args.output.exists():
        raise ValueError('Use a new output path; keep previous evidence immutable')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps(dict(status=result['status'], reads=[dict(expression=row['expression'], status=row['status'],
          writers=len(row.get('writers', [])), paths=len(row.get('writer_paths', [])), reason=row.get('reason')) for row in result['reads']])))
