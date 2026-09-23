"""Symbol, field-writer, regex-input and call indexes; all facts have source IDs."""
from __future__ import annotations

import ast
import builtins
import collections
import posixpath
import re
import textwrap
from functools import lru_cache

from .graph import Flow, json_value, standard_go_guard, standard_node_assertion
from .syntax import (ATTRS, CALLS, Source, Unit, attr_parts, call_parts, canonical,
                     child, diff_lines, is_test_path, literal, units, walk)


class Index:
    def __init__(self, sources: list[Source], patch: str, max_depth=5, max_reachable=160):
        self.sources = {s.path: s for s in sources}
        self.units: dict[str, Unit] = {}
        self.by_name = collections.defaultdict(list)
        self.by_file_name = collections.defaultdict(list)
        self.classes = set()
        self.bases = {}
        self.flows: dict[str, Flow] = {}
        self.changed_lines = diff_lines(patch)
        self.changed = set()
        self.field_units = collections.defaultdict(set)
        self.class_fields = collections.defaultdict(set)
        self.global_constants = {}
        self.regexes = {}
        self.regex_names = {}
        self.max_depth, self.max_reachable = max_depth, max_reachable
        self._return_types = {}
        self.oracle_helpers = {}
        self.parameter_regexes = collections.defaultdict(set)
        self.go_packages = {}
        self.parse_errors = [s.path for s in sources if s.root.has_error]
        for src in sources:
            found, classes = units(src)
            self.classes.update(classes)
            self.bases.update(classes)
            if src.language == 'go':
                self.go_packages[src.path] = next((src.text(n.named_children[0]) for n in src.root.named_children
                                                  if n.type == 'package_clause' and n.named_children), '')
                for n in walk(src.root):
                    if n.type == 'type_spec':
                        self.classes.add(src.text(child(n, 'name')))
            for u in found:
                self.units[u.id] = u
                self.by_name[u.name].append(u)
                self.by_file_name[src.path, u.name].append(u)
                start = u.body.start_point.row + 1 if src.language == 'typescript' else u.line
                lines = self.changed_lines.get(src.path, set())
                if (not u.test and not is_test_path(src.path) and src.origin == 'repository'
                        and any(start <= n <= u.body.end_point.row + 1 for n in lines)):
                    self.changed.add(u.id)
                if not u.test and src.origin == 'repository':
                    for n in walk(u.body, stop_functions=True):
                        if n.type in {'assignment', 'augmented_assignment', 'assignment_statement'}:
                            left = child(n, 'left')
                            if left is not None and left.type in ATTRS and u.owner:
                                obj, fld = attr_parts(left)
                                objtext = src.text(obj)
                                if objtext in {'self', 'cls'} or objtext in u.param_types:
                                    self.field_units[src.text(fld)].add(u.id)
                                    self.class_fields[u.owner, src.text(fld)].add(u.id)
                if not u.test and (is_test_path(src.path) or re.match(r'^(expect|assert)', u.name)):
                    predicates = []
                    for n in walk(u.body, stop_functions=True):
                        if standard_go_guard(u, n) is not None:
                            predicates.append('go_testing_failure_guard')
                        elif standard_node_assertion(u, n) is not None:
                            predicates.append('node_assert_import')
                        elif n.type == 'assert_statement':
                            predicates.append('assert')
                        elif n.type in CALLS:
                            fn, _ = call_parts(n)
                            name = src.text(fn)
                            if src.language == 'go' and re.match(r'^(require|assert)\.', name):
                                predicates.append(name.rsplit('.', 1)[-1])
                            elif src.language == 'typescript' and name == 'expect':
                                predicates.append('expect')
                    if predicates:
                        self.oracle_helpers[u.id] = predicates
            self._globals(src)
        # A second pass is needed because classes can be declared in later files.
        for u in self.units.values():
            self.return_types(u)
        self._propagate_regex_parameters()

    def _propagate_regex_parameters(self):
        """Propagate match-object provenance across actual/formal bindings, monotonically."""
        relevant = [u for u in self.units.values() if u.source.origin == 'repository'
                    and u.source.path in self.changed_lines and not u.test and not is_test_path(u.source.path)]
        for _ in range(4):
            dirty = set()
            for caller in relevant:
                flow = self.flow(caller.id)
                for call in flow.calls:
                    for target, reason in call.targets:
                        if reason in {'unique_name_candidate', 'ambiguous_name_candidate'}:
                            continue
                        callee = self.units[target]
                        params = [p for p in callee.params if p not in {'self', 'cls'}]
                        pairs = list(zip(params, call.args)) + list(call.keywords.items())
                        for name, value in pairs:
                            key = (target, name)
                            novel = value.regexes - self.parameter_regexes[key]
                            if novel:
                                self.parameter_regexes[key].update(novel)
                                dirty.add(target)
            if not dirty:
                break
            for uid in dirty:
                self.flows.pop(uid, None)

    def _globals(self, src):
        if src.language != 'python':
            return
        try:
            tree = ast.parse(src.code)
        except SyntaxError:
            return
        for node in tree.body:
            if not isinstance(node, (ast.Assign, ast.AnnAssign)):
                continue
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if not isinstance(target, ast.Name):
                    continue
                try:
                    self.global_constants[src.path, target.id] = (canonical(ast.literal_eval(node.value)),)
                except (ValueError, SyntaxError, TypeError):
                    pass
                value = node.value
                if (isinstance(value, ast.Call) and ast.unparse(value.func) in {'re.compile', 'regex.compile'}
                        and value.args and src.path in self.changed_lines and not is_test_path(src.path)):
                    try:
                        pattern = ast.literal_eval(value.args[0])
                        if not isinstance(pattern, str) or len(pattern) > 5000:
                            continue
                        flags = 0
                        flag_nodes = value.args[1:] + [kw.value for kw in value.keywords if kw.arg == 'flags']
                        for flag_node in flag_nodes:
                            for f in ast.walk(flag_node):
                                if isinstance(f, ast.Attribute) and f.attr in {'ASCII', 'IGNORECASE', 'MULTILINE', 'DOTALL', 'VERBOSE'}:
                                    flags |= getattr(re, f.attr)
                        compiled = re.compile(pattern, flags)
                        if not compiled.groups:
                            continue
                        key = f'{src.path}:{node.lineno}:{target.id}'
                        self.regexes[key] = compiled
                        self.regex_names[src.path, target.id] = key
                    except (ValueError, SyntaxError, TypeError, re.error):
                        continue

    def factor_key(self, regex: str, group) -> str:
        if isinstance(group, str):
            group = self.regexes[regex].groupindex.get(group, group)
        return f'{regex}#group:{group}'

    def type_names(self, text):
        return set(re.findall(r'[A-Za-z_]\w*', text)) & self.classes

    def attribute_types(self, types, field):
        result = set()
        for typ in types:
            for u in self.by_name.get(field, []):
                if u.owner == typ:
                    result.update(self.return_types(u))
        return result

    def return_types(self, unit):
        if unit.id in self._return_types:
            return self._return_types[unit.id]
        result = set(unit.return_types) & self.classes
        if unit.name in {'__init__', 'constructor'} and unit.owner:
            result.add(unit.owner)
        # Only direct returned constructors: do not infer from unrelated body calls.
        for node in walk(unit.body, stop_functions=True):
            if node.type in {'return_statement', 'yield'}:
                for call in node.named_children:
                    if call.type in CALLS:
                        fn, _ = call_parts(call)
                        name = unit.source.text(fn).split('.')[-1]
                        if name in self.classes:
                            result.add(name)
        if unit.source.language == 'python':
            try:
                function = ast.parse(textwrap.dedent(unit.source.text(unit.node))).body[0]
                for node in ast.walk(function):
                    # A comprehension's isinstance guard refines the returned element type.
                    if isinstance(node, ast.Return) and isinstance(node.value, (ast.ListComp, ast.GeneratorExp)):
                        element = ast.unparse(node.value.elt)
                        for gen in node.value.generators:
                            for guard in gen.ifs:
                                if (isinstance(guard, ast.Call) and isinstance(guard.func, ast.Name)
                                        and guard.func.id == 'isinstance' and len(guard.args) == 2
                                        and ast.unparse(guard.args[0]) == element):
                                    typ = ast.unparse(guard.args[1]).rsplit('.', 1)[-1]
                                    if typ in self.classes:
                                        result.add(typ)
            except (SyntaxError, ValueError, AttributeError):
                pass
        self._return_types[unit.id] = result
        return result

    def local_functions(self, unit, name, fixture=False):
        found = [u for u in self.by_file_name.get((unit.source.path, name), []) if not u.test]
        if not found and unit.source.written_path:
            found = [u for u in self.by_file_name.get((unit.source.written_path, name), []) if not u.test]
        if fixture:
            found = [u for u in found if any('fixture' in d for d in u.decorators)]
            if not found:
                found = [u for u in self.by_name.get(name, []) if u.source.path.endswith('conftest.py')
                         and any('fixture' in d for d in u.decorators)]
        return found

    @lru_cache(maxsize=None)
    def module_paths(self, source_path, module):
        src = self.sources[source_path]
        if src.language == 'python':
            if module.startswith('.'):
                dots = len(module) - len(module.lstrip('.'))
                base = posixpath.dirname(src.lookup_path)
                for _ in range(dots - 1):
                    base = posixpath.dirname(base)
                path = posixpath.join(base, module[dots:].replace('.', '/'))
                return [p for p in (path + '.py', path + '/__init__.py') if p in self.sources]
            suffix = module.replace('.', '/')
            return [p for p in self.sources if p in {suffix + '.py', suffix + '/__init__.py'}
                    or p.endswith('/' + suffix + '.py') or p.endswith('/' + suffix + '/__init__.py')]
        if src.language == 'typescript':
            if not module.startswith('.'):
                return []
            path = posixpath.normpath(posixpath.join(posixpath.dirname(src.lookup_path), module))
            return [p for p in (path, path + '.ts', path + '/index.ts') if p in self.sources]
        return []

    def exported(self, paths, name, visited=None):
        visited = set() if visited is None else visited
        found = []
        for path in paths:
            if path in visited:
                continue
            visited.add(path)
            found.extend(u for u in self.by_file_name.get((path, name), []) if not u.test)
            src = self.sources[path]
            for export in src.exports:
                found.extend(self.exported(self.module_paths(path, export), name, visited))
            if src.language == 'python' and name in src.imports:
                module, member = src.imports[name]
                if member:
                    found.extend(self.exported(self.module_paths(path, module), member, visited))
        return found

    def resolve(self, unit, fntext, receiver_types=(), args=()):
        name = fntext.rsplit('.', 1)[-1]
        if not re.fullmatch(r'[A-Za-z_]\w*', name):
            return []
        source = unit.source
        visible = lambda u: u.source.origin == 'repository' or u.source.path == source.path
        selected, reason = [], ''
        if (source.language == 'python' and '.' not in fntext and hasattr(builtins, name)
                and not self.local_functions(unit, name) and name not in source.imports
                and name not in self.classes):
            return []
        # Known built-in receivers cannot dispatch to an unrelated repository method.
        native = {t for t in receiver_types if t.startswith('@builtin:')}
        if native and '.' in fntext and name in {'append', 'extend', 'pop', 'get', 'items', 'keys', 'values',
                                               'update', 'add', 'split', 'join', 'replace', 'strip', 'upper', 'lower'}:
            return []
        if '.' not in fntext:
            selected = self.local_functions(unit, name)
            reason = 'local_symbol'
            if not selected and name in source.imports:
                mod, imported = source.imports[name]
                selected = self.exported(self.module_paths(source.path, mod), imported or name)
                reason = 'import_symbol'
            if not selected and name in self.classes:
                selected = [u for u in self.by_name.get('__init__', []) if u.owner == name and visible(u)]
                reason = 'constructor'
        else:
            root = fntext.split('.', 1)[0]
            if root in source.imports:
                mod, imported = source.imports[root]
                if source.language == 'go':
                    # Same repository Go package functions; external packages stay unresolved.
                    package = re.sub(r'/v\d+$', '', mod).rsplit('/', 1)[-1]
                    selected = [u for u in self.by_name.get(name, []) if not u.owner and not u.test
                                and u.source.origin == 'repository' and not is_test_path(u.source.path)
                                and self.go_packages.get(u.source.path) == package]
                    reason = 'package_symbol'
                else:
                    module = mod + ('.' + imported if imported else '')
                    selected = self.exported(self.module_paths(source.path, module), name)
                    if not selected:
                        selected = self.exported(self.module_paths(source.path, mod), name)
                    reason = 'import_symbol'
                # Imported class constructor, e.g. events.Key.
                if not selected and name in self.classes:
                    selected = [u for u in self.by_name.get('__init__', []) if u.owner == name and visible(u)]
                    reason = 'constructor'
            types = set(receiver_types)
            if root in {'self', 'cls'} and unit.owner:
                types.add(unit.owner)
                changed = True
                while changed:
                    before = len(types)
                    types.update(cls for cls, bases in self.bases.items() if set(bases) & types)
                    changed = len(types) != before
            # Include inherited implementations and virtual overrides conservatively.
            for typ in list(types):
                types.update(self.bases.get(typ, []))
            if not selected and types:
                selected = [u for u in self.by_name.get(name, []) if u.owner in types and not u.test and visible(u)]
                reason = 'receiver_type'
            # Framework dispatch model: literal magic name must resolve to an actual decorator.
            if name in {'run_line_magic', 'run_cell_magic'} and args and args[0].constants:
                kind = 'line_magic' if name == 'run_line_magic' else 'cell_magic'
                dispatched = []
                for arg in args[0].constants:
                    val = json_value(arg)
                    if isinstance(val, str):
                        dispatched.extend(u for u in self.by_name.get(val, []) if visible(u) and any(kind in d for d in u.decorators))
                if dispatched:
                    selected = dispatched
                    reason = 'literal_registered_dispatch'
        if not selected:
            candidates = [u for u in self.by_name.get(name, []) if not u.test and u.source.origin == 'repository']
            # Never promote a same-spelling unresolved method into a resolved symbol.
            if len(candidates) == 1:
                selected, reason = candidates, 'unique_name_candidate'
            elif 1 < len(candidates) <= 12:
                selected, reason = candidates, 'ambiguous_name_candidate'
        return [(u.id, reason) for u in sorted({u.id: u for u in selected}.values(), key=lambda u: u.id)]

    def flow(self, uid):
        if uid not in self.flows:
            self.flows[uid] = Flow(self, self.units[uid])
        return self.flows[uid]

    @lru_cache(maxsize=None)
    def reach(self, uid):
        todo = collections.deque([(uid, 0, ())])
        seen, changed, paths = set(), {}, {}
        truncated = False
        while todo:
            current, depth, path = todo.popleft()
            if current in seen:
                continue
            if len(seen) >= self.max_reachable:
                truncated = True
                break
            seen.add(current)
            paths[current] = path
            if current in self.changed:
                changed[current] = path
            if depth >= self.max_depth:
                truncated = True
                continue
            flow = self.flow(current)
            for call in flow.calls:
                for target, reason in call.targets:
                    if target not in seen:
                        edge = (current, flow.nodes[call.node]['line'], target, reason)
                        todo.append((target, depth + 1, path + (edge,)))
        return {'seen': seen, 'changed': changed, 'paths': paths, 'truncated': truncated}

    def field_witnesses(self, fields, reachable, typed_fields=None):
        found = []
        typed_fields = typed_fields or {}
        for name in fields:
            typed = set().union(*(self.class_fields.get((typ, name), set()) for typ in typed_fields.get(name, [])))
            for uid in sorted((self.field_units.get(name, set()) & reachable) | typed):
                flow = self.flow(uid)
                for root in flow.fields.get(name, []):
                    sliced = flow.slice([root])
                    lines = self.changed_lines.get(flow.source.path, set())
                    changed = [i for i in sliced if any(flow.nodes[i]['line'] <= n <= flow.nodes[i]['end_line'] for n in lines)]
                    if changed:
                        params = {flow.nodes[i]['parameter'] for i in sliced if 'parameter' in flow.nodes[i]}
                        found.append({'symbol': uid, 'owner': flow.unit.owner, 'field': name,
                                      'line': flow.nodes[root]['line'], 'parameters': sorted(params),
                                      'basis': 'receiver_type_may_definition' if uid in typed else 'reachable_writer'})
        return found

    @lru_cache(maxsize=None)
    def field_factors(self, uid, name):
        """Project changed constructor field dependencies back to regex capture groups."""
        flow = self.flow(uid)
        roots = flow.fields.get(name, [])
        sliced = flow.slice(roots)
        params = {flow.nodes[i]['parameter'] for i in sliced if 'parameter' in flow.nodes[i]}
        result = set()
        # Demand is limited to modified production files, not arbitrary whole-repo pairs.
        for caller in self.units.values():
            if caller.test or caller.source.origin != 'repository' or caller.source.path not in self.changed_lines or is_test_path(caller.source.path):
                continue
            cf = self.flow(caller.id)
            for call in cf.calls:
                if uid not in {t for t, _ in call.targets}:
                    continue
                positional_params = [p for p in flow.unit.params if p not in {'self', 'cls'}]
                for param in params:
                    value = call.keywords.get(param)
                    if value is None and param in positional_params:
                        i = positional_params.index(param)
                        value = call.args[i] if i < len(call.args) else None
                    if value is not None:
                        for node in cf.slice([value.id]):
                            if 'factor' in cf.nodes[node]:
                                result.add(cf.nodes[node]['factor'])
        return frozenset(result)

    def regex_bindings(self, values):
        result = collections.defaultdict(set)
        for raw in values:
            value = json_value(raw)
            if not isinstance(value, str) or len(value) > 512:
                continue
            for key, regex in self.regexes.items():
                match = regex.fullmatch(value)
                if match:
                    for i, group in enumerate(match.groups(), 1):
                        result[self.factor_key(key, i)].add(canonical(group))
        return dict(result)
