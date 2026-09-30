"""Bounded source guards for a resolved Python owned-member call.

``None`` means no dispatch hazard was found in these source facts; it is not a
whole-language dispatch proof.  The caller must already prove the callee/class
resolution and must still bind arguments and analyze returned dependencies.
This guard rejects visible class/member replacement, receiver escapes/effects,
and unsupported Python lookup/construction hooks.  It neither executes a
subject nor infers heap behavior, contracts, or expected values.
"""
from __future__ import annotations

import ast

_SCOPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)
_COMPREHENSIONS = (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)


def _owned(nodes):
    """Visit lexical scope facts, retaining declarations but not their bodies."""
    for node in nodes:
        yield node
        if not isinstance(node, _SCOPES + _COMPREHENSIONS):
            yield from _owned(ast.iter_child_nodes(node))


def _targets(node):
    if isinstance(node, (ast.Assign, ast.Delete)):
        return node.targets
    if isinstance(node, ast.AnnAssign):
        return [node.target] if node.value is not None else []
    if isinstance(node, (ast.AugAssign, ast.NamedExpr, ast.For, ast.AsyncFor)):
        return [node.target]
    if isinstance(node, (ast.With, ast.AsyncWith)):
        return [item.optional_vars for item in node.items if item.optional_vars is not None]
    return []


def _bindings(node):
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return {node.name}
    if isinstance(node, (ast.Import, ast.ImportFrom)):
        return {item.asname or (item.name.split('.')[0] if isinstance(node, ast.Import) else item.name)
                for item in node.names}
    if isinstance(node, ast.ExceptHandler) and node.name:
        return {node.name}
    return {item.id for target in _targets(node) for item in ast.walk(target)
            if isinstance(item, ast.Name) and isinstance(item.ctx, (ast.Store, ast.Del))}


def _member_targets(node, name):
    return [item for target in _targets(node) for item in ast.walk(target)
            if isinstance(item, ast.Attribute) and item.attr == name
            and isinstance(item.ctx, (ast.Store, ast.Del))]


def _parse(source):
    tree = ast.parse(source.code)
    offsets = [0]
    for line in source.data.splitlines(keepends=True):
        offsets.append(offsets[-1] + len(line))
    return tree, offsets


def _span(node, offsets):
    return (offsets[node.lineno - 1] + node.col_offset,
            offsets[node.end_lineno - 1] + node.end_col_offset)


def _enclosing_class(target, tree):
    node = target.node.parent
    while node is not None and node.type != 'class_definition':
        node = node.parent
    if node is None:
        return None
    found = [item for item in ast.walk(tree) if isinstance(item, ast.ClassDef)
             and item.lineno == node.start_point.row + 1
             and item.col_offset == node.start_point.column]
    return found[0] if len(found) == 1 else None


def _module_class_symbols(index, path, name, seen=None):
    """Resolve declaration/import facts without treating attribute stores as names.

    No assignment aliases, wildcard imports, or competing name bindings are
    interpreted. Those remain unavailable facts, never same-name fallbacks.
    """
    seen = set() if seen is None else set(seen)
    if (path, name) in seen or path not in index.sources:
        return set()
    seen.add((path, name))
    source = index.sources[path]
    tree, _ = _parse(source)
    declarations = [node for node in _owned(tree.body) if name in _bindings(node)]
    if len(declarations) != 1:
        return set()
    declaration = declarations[0]
    if isinstance(declaration, ast.ClassDef):
        return {(path, declaration.name)}
    if isinstance(declaration, ast.ImportFrom):
        imported = source.imports.get(name)
        if imported and imported[1] is not None:
            return set().union(*(_module_class_symbols(index, target, imported[1], seen)
                                 for target in index.module_paths(path, imported[0])))
    return set()


def _class_symbols(index, unit, expression, *, module_scope=False):
    if not isinstance(expression, (ast.Name, ast.Attribute)):
        return set()
    parts = ast.unparse(expression).split('.')
    name = parts[0]
    tree, _ = _parse(unit.source)
    if not module_scope:
        declarations = [node for node in ast.walk(tree)
                        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                        and node.lineno == unit.node.start_point.row + 1
                        and node.col_offset == unit.node.start_point.column]
        if len(declarations) != 1 or name in unit.params:
            return set()
        if any(name in _bindings(node) for node in _owned(declarations[0].body)):
            return set()
    if len(parts) == 1:
        return _module_class_symbols(index, unit.source.path, name)
    imported = unit.source.imports.get(name)
    module_bindings = [node for node in _owned(tree.body) if name in _bindings(node)]
    if len(module_bindings) != 1 or not isinstance(module_bindings[0], (ast.Import, ast.ImportFrom)):
        return set()
    if imported and imported[1] is None:
        written_module = '.'.join(parts[:-1])
        module = (written_module if written_module == imported[0] or written_module.startswith(imported[0] + '.')
                  else imported[0] + ('.' + '.'.join(parts[1:-1]) if len(parts) > 2 else ''))
        return set().union(*(_module_class_symbols(index, path, parts[-1])
                             for path in index.module_paths(unit.source.path, module)))
    return set()


def _origins_classes(index, unit, origins):
    return set().union(*(_class_symbols(index, unit, ast.Name(id=name, ctx=ast.Load()))
                         for kind, name in origins if kind == 'global'))


def _receiver_origins(flow, nid, memo=None, active=None):
    """Transparent local aliases share an allocation/formal origin, not a name."""
    memo = {} if memo is None else memo
    active = set() if active is None else set(active)
    if nid in memo:
        return memo[nid]
    if nid in active or not 0 <= nid < len(flow.nodes):
        return set(), True
    active.add(nid)
    node = flow.nodes[nid]
    kind = node['kind']
    if kind == 'global':
        result = ({('global', node.get('variable', node['text']))}, False)
    elif kind in {'call', 'parameter', 'receiver'}:
        result = ({('node', nid)}, False)
    elif kind in {'read', 'definition', 'join', 'may_effect'}:
        origins = set(); hazard = kind in {'join', 'may_effect'}
        for dependency in flow.edges.get(nid, ()):
            inherited, unknown = _receiver_origins(flow, dependency, memo, active)
            origins.update(inherited); hazard |= unknown
        result = origins, hazard or not origins
    else:
        result = set(), True
    memo[nid] = result
    return result


def _constructor_unknown(index, target, klass, receiver_is_instance):
    constructors = [unit for unit in index.units.values()
                    if unit.source.path == target.source.path and unit.owner == target.owner
                    and unit.name == '__init__']
    for constructor in constructors:
        tree, offsets = _parse(constructor.source)
        declarations = [node for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                        and node.lineno == constructor.node.start_point.row + 1
                        and node.col_offset == constructor.node.start_point.column]
        if len(declarations) != 1:
            return 'receiver_constructor_source_unknown'
        declaration = declarations[0]
        if declaration.decorator_list:
            return 'receiver_constructor_descriptor_unknown'
        positional = [*declaration.args.posonlyargs, *declaration.args.args]
        if not positional:
            return 'receiver_constructor_formal_unknown'
        first = positional[0].arg
        constructor_flow = index.flow(constructor.id)
        # env may already include later writes. Locate the original formal.
        formals = [row['id'] for row in constructor_flow.nodes
                   if row['kind'] in {'parameter', 'receiver'}
                   and (row.get('parameter') == first or row['text'] == first)]
        if not formals:
            return 'receiver_constructor_formal_unknown'
        initial_origins = set().union(*(_receiver_origins(constructor_flow, nid)[0] for nid in formals))
        for node in _owned(declaration.body):
            for member in _member_targets(node, target.name):
                if isinstance(member.value, ast.Name) and member.value.id == klass.name:
                    return 'receiver_constructor_class_member_write'
                left, right = _span(member.value, offsets)
                values = [row['id'] for row in constructor_flow.nodes
                          if row['start_byte'] == left and row['end_byte'] == right
                          and row['kind'] == 'read']
                if any((target.source.path, klass.name) in _origins_classes(
                        index, constructor, _receiver_origins(constructor_flow, nid)[0]) for nid in values):
                    return 'receiver_constructor_class_member_write'
                if not receiver_is_instance:
                    continue
                if any(_receiver_origins(constructor_flow, nid)[0] & initial_origins for nid in values):
                    return 'receiver_constructor_member_write'
                if not values:
                    return 'receiver_constructor_member_alias_unknown'
        if receiver_is_instance:
            for inner in constructor_flow.calls:
                actuals = [*inner.args, *inner.keywords.values()]
                if inner.receiver is not None:
                    actuals.append(inner.receiver)
                if any(_receiver_origins(constructor_flow, actual.id)[0] & initial_origins
                       for actual in actuals):
                    return 'receiver_constructor_opaque_escape'
    return None


def dispatch_unknown(index, caller_unit, flow, call, target):
    """Return a source dispatch hazard or None for a uniquely resolved target.

    Owned Python methods only.  Receiver-free bound aliases, inherited/custom
    metaclass dispatch, custom lookup/allocation hooks, unknown descriptors,
    constructor escapes, and prior receiver effects are outside this scope.
    Unrelated fresh local objects are not equated merely by class/member names.
    """
    if target.source.language != 'python' or not target.owner:
        return None
    if caller_unit.source.language != 'python':
        return 'receiver_cross_language_unknown'
    if call.receiver is None:
        return 'receiver_source_value_unavailable'
    try:
        tree, _ = _parse(target.source)
        klass = _enclosing_class(target, tree)
        if klass is None:
            return 'receiver_enclosing_class_unknown'
        if klass.decorator_list:
            return 'receiver_class_decorator_unknown'
        if klass.keywords:
            return 'receiver_metaclass_unknown'
        module_names = set().union(*(_bindings(node) for node in _owned(tree.body)))
        if any(not isinstance(base, ast.Name) or base.id != 'object'
               or 'object' in target.source.imports or 'object' in module_names
               for base in klass.bases):
            return 'receiver_inherited_dispatch_unknown'
        class_nodes = list(_owned(klass.body))
        for node in class_nodes:
            if target.name not in _bindings(node):
                continue
            if (isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and node.lineno == target.node.start_point.row + 1
                    and node.col_offset == target.node.start_point.column):
                continue
            return 'receiver_class_member_rebound'
        methods = [node for node in klass.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))]
        if any(node.name in {'__new__', '__getattribute__', '__getattr__', '__setattr__'} for node in methods):
            return 'receiver_custom_lookup_or_allocation_unknown'
        method = next((node for node in methods if node.lineno == target.node.start_point.row + 1
                       and node.col_offset == target.node.start_point.column), None)
        if method is None:
            return 'receiver_member_source_unknown'
        if method.decorator_list:
            if (len(method.decorator_list) != 1 or not isinstance(method.decorator_list[0], ast.Name)
                    or method.decorator_list[0].id not in {'classmethod', 'staticmethod'}):
                return 'receiver_member_descriptor_unknown'
            name = method.decorator_list[0].id
            if (name in module_names or name in target.source.imports
                    or any(name in _bindings(node) for node in class_nodes)):
                return 'receiver_descriptor_builtin_shadowed'
        actual_origins, effect = _receiver_origins(flow, call.receiver.id)
        if effect or not actual_origins:
            return 'receiver_prior_effect_or_alias_unknown'
        receiver_is_instance = any(kind == 'node' for kind, _ in actual_origins)
        reason = _constructor_unknown(index, target, klass, receiver_is_instance)
        if reason:
            return reason
        # Module execution precedes test invocation, even when a monkeypatch is
        # lexically after the test's definition. Do not enter other function bodies.
        wanted = (target.source.path, klass.name)
        for source in {target.source.path: target.source, caller_unit.source.path: caller_unit.source}.values():
            parsed, _ = _parse(source)
            for node in _owned(parsed.body):
                for member in _member_targets(node, target.name):
                    if (source.path == target.source.path and isinstance(member.value, ast.Name)
                            and member.value.id == klass.name):
                        return 'receiver_module_member_write'
                    source_unit = target if source.path == target.source.path else caller_unit
                    symbols = _class_symbols(index, source_unit, member.value, module_scope=True)
                    if wanted in symbols:
                        return 'receiver_module_member_write'
                    if not symbols:
                        return 'receiver_module_member_alias_unknown'
        caller_tree, offsets = _parse(caller_unit.source)
        bodies = [node for node in ast.walk(caller_tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                  and node.lineno == caller_unit.node.start_point.row + 1
                  and node.col_offset == caller_unit.node.start_point.column]
        if len(bodies) != 1:
            return 'receiver_caller_scope_unknown'
        call_start = flow.nodes[call.node]['start_byte']
        by_extent = {}
        for row in flow.nodes:
            if row['kind'] == 'read':
                by_extent.setdefault((row['start_byte'], row['end_byte']), []).append(row['id'])
        for node in _owned(bodies[0].body):
            for member in _member_targets(node, target.name):
                if _span(member, offsets)[1] > call_start:
                    continue
                values = by_extent.get(_span(member.value, offsets), [])
                if any(_receiver_origins(flow, nid)[0] & actual_origins for nid in values):
                    return 'receiver_visible_member_write'
                if wanted in _class_symbols(index, caller_unit, member.value):
                    return 'receiver_visible_class_member_write'
                if not values and not _class_symbols(index, caller_unit, member.value):
                    return 'receiver_member_write_alias_unknown'
        for earlier in flow.calls:
            if flow.nodes[earlier.node]['end_byte'] > call_start:
                continue
            actuals = [*earlier.args, *earlier.keywords.values()]
            if earlier.receiver is not None:
                actuals.append(earlier.receiver)
            if any(_receiver_origins(flow, actual.id)[0] & actual_origins for actual in actuals):
                return 'receiver_prior_opaque_escape'
        return None
    except (SyntaxError, ValueError, TypeError, KeyError, AttributeError, IndexError, RecursionError):
        return 'receiver_source_analysis_unknown'
