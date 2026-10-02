"""Recover bounded example tests through a changed call's source binding.

Only Python tests in the same complete source module are considered. This is
context retrieval, not oracle validation or a proof that two calls are
semantically equivalent. Production bodies and fetched documentation text are
never returned. Literal similarity ranks already binding-matched examples;
issue text, outcomes, labels and candidate identifiers play no part.
"""
from __future__ import annotations

import ast
from collections import Counter
from difflib import SequenceMatcher
import hashlib
import re
from types import SimpleNamespace


VERSION = 'same-binding-source-controls.v2'
POLICY = dict(
    scope='original Python module-level test_ definitions; modified source supplies edited-call seeds only',
    seeds='calls whose argument overlaps a non-oracle edit',
    identity='same unique fixture declaration and method; explicit imported API; local function declaration',
    ranking='fixture identity first, then maximum contiguous literal fragment length, then source order',
    literals='matched actual arguments and at most four backward unique assignment/loop bindings; first 64 literals of at most 256 characters; unrelated expectations never scanned',
    added_imports='suppress context when candidate-added imports are not revalidated',
    validation_adapters='pytest raises/warns/deprecated_call/approx/fail are not input-call identities; their mixed actual/expected arguments are unmodelled',
    docs='module header URLs of receiver constructor/API plus one unique local import hop; links only',
    validity='examples only; no expectation transfer or semantic equivalence is proved',
)
_URL = re.compile(r'https?://[^\s<>\"\'`]+')
_FUNCTIONS = (ast.FunctionDef, ast.AsyncFunctionDef)
_ORACLE_ROLES = {'expected', 'semantic_expected', 'oracle'}


def _walk(node):
    """Visit one lexical function body, without entering nested definitions."""
    yield node
    for child in ast.iter_child_nodes(node):
        if isinstance(child, (*_FUNCTIONS, ast.ClassDef, ast.Lambda)):
            yield child
            continue
        yield from _walk(child)


def _offsets(code):
    offsets = [0]
    for line in code.splitlines(keepends=True):
        offsets.append(offsets[-1] + len(line.encode()))
    return offsets


def _span(node, path, offsets, decorated=False, version='modified'):
    first = min([node, *getattr(node, 'decorator_list', [])], key=lambda n: (n.lineno, n.col_offset)) if decorated else node
    start = offsets[first.lineno - 1] + first.col_offset
    if decorated and first is not node:
        start -= 1  # include the @ token preceding the decorator expression
    return dict(path=path, start_byte=start,
                end_byte=offsets[node.end_lineno - 1] + node.end_col_offset,
                line=first.lineno, end_line=node.end_lineno, version=version)


def _overlap(a, b):
    return a['path'] == b['path'] and a['start_byte'] < b['end_byte'] and b['start_byte'] < a['end_byte']


def _module_bindings(tree):
    """Count visible module writes, without treating function locals as globals."""
    names = Counter()
    wildcard = False
    for node in _walk(tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
            names[node.id] += 1
        elif isinstance(node, (*_FUNCTIONS, ast.ClassDef)):
            names[node.name] += 1
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                wildcard |= alias.name == '*'
                names[alias.asname or alias.name.split('.')[0]] += 1
        elif isinstance(node, ast.ExceptHandler) and node.name:
            names[node.name] += 1
        elif isinstance(node, (ast.MatchAs, ast.MatchStar)) and node.name:
            names[node.name] += 1
        elif isinstance(node, ast.MatchMapping) and node.rest:
            names[node.rest] += 1
    return names, wildcard


def _imports(tree):
    counts, wildcard = _module_bindings(tree)
    if wildcard:
        return {}
    result, ambiguous, bindings = {}, set(), set()
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                name = alias.asname or alias.name.split('.')[0]
                if name in result:
                    ambiguous.add(name)
                result[name] = (alias.name if alias.asname else alias.name.split('.')[0], None)
        elif isinstance(node, ast.ImportFrom) and node.level == 0:
            for alias in node.names:
                if alias.name != '*':
                    name = alias.asname or alias.name
                    if name in result:
                        ambiguous.add(name)
                    result[name] = (node.module, alias.name)
                else:
                    return {}  # wildcard binding order is deliberately unmodelled
        elif isinstance(node, (*_FUNCTIONS, ast.ClassDef)):
            bindings.add(node.name)
        else:
            for nested in _walk(node):
                if isinstance(nested, ast.Name) and isinstance(nested.ctx, (ast.Store, ast.Del)):
                    bindings.add(nested.id)
                elif isinstance(nested, (ast.Import, ast.ImportFrom)):
                    if any(alias.name == '*' for alias in nested.names):
                        return {}
                    bindings.update(alias.asname or alias.name.split('.')[0] for alias in nested.names)
                elif isinstance(nested, (*_FUNCTIONS, ast.ClassDef)):
                    bindings.add(nested.name)
    return {name: value for name, value in result.items() if name not in ambiguous | bindings and counts[name] == 1}


def _chain(node):
    if isinstance(node, ast.Name):
        return [node.id]
    if isinstance(node, ast.Attribute):
        before = _chain(node.value)
        if before:
            return before + [node.attr]
    return None


def _import_symbol(node, imports, blocked):
    parts = _chain(node)
    if not parts or parts[0] in blocked or parts[0] not in imports:
        return None
    module, symbol = imports[parts[0]]
    return module, '.'.join(([symbol] if symbol else []) + parts[1:])


def _names(function):
    parameters = {arg.arg for arg in [*function.args.posonlyargs, *function.args.args, *function.args.kwonlyargs]}
    parameters.update(arg.arg for arg in (function.args.vararg, function.args.kwarg) if arg)
    stored = {node.id for node in _walk(function) if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del))}
    for node in _walk(function):
        if isinstance(node, (*_FUNCTIONS, ast.ClassDef)) and node is not function:
            stored.add(node.name)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            stored.update(alias.asname or alias.name.split('.')[0] for alias in node.names)
        elif isinstance(node, ast.ExceptHandler) and node.name:
            stored.add(node.name)
        elif isinstance(node, (ast.MatchAs, ast.MatchStar)) and node.name:
            stored.add(node.name)
        elif isinstance(node, ast.MatchMapping) and node.rest:
            stored.add(node.rest)
        elif isinstance(node, (ast.Global, ast.Nonlocal)):
            stored.update(node.names)
    # Parameters participate in name lookup, but fixture parameters are allowed
    # separately if they have not also been rebound in the function body.
    return parameters, stored, parameters | stored


def _parametrized(function):
    result = set()
    for decorator in function.decorator_list:
        if not isinstance(decorator, ast.Call) or not decorator.args:
            continue
        parts = _chain(decorator.func)
        if not parts or parts[-1] != 'parametrize':
            continue
        names = decorator.args[0]
        if isinstance(names, ast.Constant) and isinstance(names.value, str):
            result.update(x.strip() for x in names.value.split(','))
        elif isinstance(names, (ast.Tuple, ast.List)):
            result.update(x.value for x in names.elts if isinstance(x, ast.Constant) and isinstance(x.value, str))
    return result


def _injectable_parameters(function):
    positional = [*function.args.posonlyargs, *function.args.args]
    required = {arg.arg for arg in positional[:len(positional) - len(function.args.defaults)]}
    required -= {arg.arg for arg in function.args.posonlyargs}
    required.update(arg.arg for arg, default in zip(function.args.kwonlyargs, function.args.kw_defaults) if default is None)
    return required


def _fixtures(functions, imports):
    found = {}
    for function in functions:
        for decorator in function.decorator_list:
            callee = decorator.func if isinstance(decorator, ast.Call) else decorator
            if _import_symbol(callee, imports, set()) != ('pytest', 'fixture'):
                continue
            name = function.name
            if isinstance(decorator, ast.Call):
                for keyword in decorator.keywords:
                    if keyword.arg == 'name':
                        if not isinstance(keyword.value, ast.Constant) or not isinstance(keyword.value.value, str):
                            name = None
                        else:
                            name = keyword.value.value
            if name:
                found.setdefault(name, []).append(function)
    return {name: rows[0] for name, rows in found.items() if len(rows) == 1
            and sum(f.name == rows[0].name for f in functions) == 1}


def _input_literals(call, function):
    """A bounded backward syntax slice of this call's actual arguments.

    Multiple prior definitions are ambiguous and contribute no propagated
    literal. Unrelated setup/oracle assignments are never visited.
    """
    definitions = {}
    for node in _walk(function):
        target = value = None
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            target, value = node.targets[0], node.value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            target, value = node.target, node.value
        elif isinstance(node, (ast.For, ast.AsyncFor)) and isinstance(node.target, ast.Name):
            target, value = node.target, node.iter
        elif isinstance(node, (ast.AugAssign, ast.NamedExpr)) and isinstance(node.target, ast.Name):
            target = node.target  # deliberately not propagated
        if target is not None:
            definitions.setdefault(target.id, []).append((target, value))
    values = []
    def collect(node, hops=0, seen=frozenset()):
        if node is None or len(values) >= 64:
            return
        if isinstance(node, ast.Constant) and isinstance(node.value, (str, bytes)):
            value = node.value if isinstance(node.value, str) else node.value.decode('latin1')
            if 2 <= len(value) <= 256:
                values.append(value)
        elif isinstance(node, ast.Name) and hops < 4 and node.id not in seen:
            prior = [(target, value) for target, value in definitions.get(node.id, [])
                     if (target.lineno, target.col_offset) < (node.lineno, node.col_offset)]
            if len(prior) == 1:
                collect(prior[0][1], hops + 1, seen | {node.id})
        elif isinstance(node, ast.Call):
            for argument in [*node.args, *(k.value for k in node.keywords)]:
                collect(argument, hops, seen)
        elif not isinstance(node, (*_FUNCTIONS, ast.ClassDef, ast.Lambda)):
            for child in ast.iter_child_nodes(node):
                collect(child, hops, seen)
    for argument in [*call.args, *(keyword.value for keyword in call.keywords)]:
        collect(argument)
    return values


def _similarity(left, right):
    return max((SequenceMatcher(None, a, b, autojunk=False).find_longest_match().size
                for a in left for b in right), default=0)


def _identity(call, function, fixtures, imports, functions, path, offsets):
    parameters, assigned, stored = _names(function)
    parts = _chain(call.func)
    if not parts:
        return None
    if len(parts) == 2 and parts[0] in _injectable_parameters(function) and parts[0] in fixtures:
        if parts[0] in assigned or parts[0] in _parametrized(function):
            return None
        fixture = fixtures[parts[0]]
        signature = hashlib.sha256(ast.dump(fixture, include_attributes=False).encode()).hexdigest()
        return dict(key=('fixture', path, fixture.name, signature, parts[1]), kind='same_fixture_definition_and_method',
                    priority=1, fixture=fixture)
    imported = _import_symbol(call.func, imports, parameters | stored)
    if imported and imported[1]:
        if imported[0] == 'pytest' and imported[1] in {'raises', 'warns', 'deprecated_call', 'approx', 'fail'}:
            return None
        return dict(key=('import', *imported), kind='same_explicit_import_binding', priority=0,
                    module=imported[0])
    if len(parts) == 1 and parts[0] not in parameters | stored and len(functions.get(parts[0], [])) == 1:
        declaration = functions[parts[0]][0]
        signature = hashlib.sha256(ast.dump(declaration, include_attributes=False).encode()).hexdigest()
        return dict(key=('local', path, declaration.name, signature),
                    kind='same_local_function_declaration', priority=0)
    return None


def _module_source(module, sources):
    suffix = module.replace('.', '/')
    found = [s for s in sources if s.path == suffix + '.py' or s.path.endswith('/' + suffix + '.py')
             or s.path == suffix + '/__init__.py' or s.path.endswith('/' + suffix + '/__init__.py')]
    return found[0] if len(found) == 1 else None


def _header_urls(source):
    """Only initial comments/docstring, not implementation literals or bodies."""
    try:
        tree = ast.parse(source.code)
    except (SyntaxError, ValueError, RecursionError):
        return [], []
    lines = source.code.splitlines(keepends=True)
    end = tree.body[0].lineno - 1 if tree.body else len(lines)
    if tree.body and isinstance(tree.body[0], ast.Expr) and isinstance(tree.body[0].value, ast.Constant) and isinstance(tree.body[0].value.value, str):
        end = tree.body[0].end_lineno
    header = ''.join(lines[:min(end, 40)])
    links = []
    for match in _URL.finditer(header):
        url = match.group().rstrip('.,;)')
        start = len(header[:match.start()].encode())
        links.append(dict(url=url, span=dict(path=source.path, start_byte=start, end_byte=start + len(url.encode()), version='original'),
                          source='repository_comment_or_docstring_link', fetched=False,
                          normative_status='not_established_by_link_alone'))
    return links, sorted({module for module, _ in _imports(tree).values() if module})


def analyze(corpus, frontend, candidate, *, max_controls=3, max_control_bytes=8000, max_urls=4):
    from relation_search.admission import program_candidate
    from relation_search.oracle_evidence import _modified_sources

    result = dict(version=VERSION, policy=POLICY, controls=[], documentation_links=[], unknowns=[],
                  semantics='source examples only; neither oracle validity nor call equivalence is proved')
    if corpus.get('language') != 'python':
        return dict(result, status='unsupported_language')
    if any(type(value) is not int or value < 0 for value in (max_controls, max_control_bytes, max_urls)):
        raise ValueError('context budgets must be nonnegative integers')
    try:
        candidate = program_candidate(candidate)
        if candidate.get('imports'):
            return dict(result, status='unknown_added_import_bindings',
                        unknowns=[dict(reason='candidate_added_imports_not_revalidated')])
        sources, owner, changes, *_ = _modified_sources(corpus, candidate)
        tree = ast.parse(owner.code)
        offsets = _offsets(owner.code)
        functions = [n for n in tree.body if isinstance(n, _FUNCTIONS)]
        counts, wildcard = _module_bindings(tree)
        named = {}
        for function in functions:
            if counts[function.name] == 1 and not wildcard:
                named.setdefault(function.name, []).append(function)
        selected = corpus['tests'][candidate['base_test_id']]
        definition = selected.get('definition_span', selected['span'])
        roots = [f for f in functions if _span(f, owner.path, offsets)['start_byte'] == definition['start_byte']]
        if len(roots) != 1 or counts[roots[0].name] != 1 or wildcard:
            return dict(result, status='unknown_root_scope')
        root = roots[0]
        imports = _imports(tree)
        fixtures = _fixtures([f for f in functions if counts[f.name] == 1], imports)
        original_code = corpus['sources'][owner.path]['code']
        original_data = original_code.encode()
        original_tree = ast.parse(original_code)
        original_offsets = _offsets(original_code)
        original_counts, original_wildcard = _module_bindings(original_tree)
        original_functions = [f for f in original_tree.body if isinstance(f, _FUNCTIONS)
                              and original_counts[f.name] == 1 and not original_wildcard]
        original_named = {f.name: [f] for f in original_functions}
        original_imports = _imports(original_tree)
        original_fixtures = _fixtures(original_functions, original_imports)
        seeds = []
        for node in _walk(root):
            if not isinstance(node, ast.Call):
                continue
            args = [*node.args, *(k.value for k in node.keywords)]
            if not any(_overlap(_span(arg, owner.path, offsets), e['span']) for arg in args
                       for e in changes if e.get('role', 'input') not in _ORACLE_ROLES):
                continue
            identity = _identity(node, root, fixtures, imports, named, owner.path, offsets)
            if identity:
                seeds.append((node, identity))
            else:
                result['unknowns'].append(dict(reason='edited_call_binding_not_established', span=_span(node, owner.path, offsets)))
        ranked, modules = [], set()
        for function in original_functions:
            position = _span(function, owner.path, original_offsets, decorated=True, version='original')
            if _overlap(position, selected['span']) or not function.name.startswith('test_'):
                continue
            matches = []
            for call in _walk(function):
                if not isinstance(call, ast.Call):
                    continue
                identity = _identity(call, function, original_fixtures, original_imports,
                                     original_named, owner.path, original_offsets)
                if not identity:
                    continue
                for changed_call, seed in seeds:
                    if identity['key'] == seed['key']:
                        matches.append((changed_call, call, identity))
            if not matches:
                continue
            score = max(m[2]['priority'] for m in matches), max(
                _similarity(_input_literals(changed, root), _input_literals(example, function))
                for changed, example, _ in matches)
            code = original_data[position['start_byte']:position['end_byte']].decode()
            records = []
            for changed_call, call, identity in matches:
                record = dict(identity=list(identity['key']), basis=identity['kind'],
                              changed_call=_span(changed_call, owner.path, offsets),
                              example_call=_span(call, owner.path, original_offsets, version='original'), equivalence_proved=False)
                if 'fixture' in identity:
                    fixture = identity['fixture']
                    extent = _span(fixture, owner.path, original_offsets, decorated=True, version='original')
                    record['fixture'] = dict(span=extent, code=original_data[extent['start_byte']:extent['end_byte']].decode(),
                                             source_version='original')
                    returned = [n.value for n in _walk(fixture) if isinstance(n, ast.Return)]
                    if len(returned) == 1 and isinstance(returned[0], ast.Call):
                        symbol = _import_symbol(returned[0].func, original_imports, _names(fixture)[2])
                        if symbol:
                            modules.add(symbol[0])
                elif 'module' in identity:
                    modules.add(identity['module'])
                records.append(record)
            ranked.append((score, position['start_byte'], dict(name=function.name, span=position, code=code,
                source_version='original', matches=records, literal_fragment_score=score[1], oracle_validity='unconfirmed_source_example')))
        used = 0
        for score, _, row in sorted(ranked, key=lambda r: (-r[0][0], -r[0][1], r[1])):
            if len(result['controls']) >= max_controls:
                break
            size = len(row['code'].encode()) + sum(len(m.get('fixture', {}).get('code', '').encode()) for m in row['matches'])
            if used + size > max_control_bytes:
                continue
            result['controls'].append(row)
            used += size
        links = []
        visited = set()
        original_sources = [SimpleNamespace(path=path, code=row['code']) for path, row in corpus['sources'].items()]
        for module in sorted(modules):
            source = _module_source(module, original_sources)
            if source is None:
                continue
            current, children = _header_urls(source)
            links.extend(current)
            visited.add(source.path)
            for child in children:
                nested = _module_source(child, original_sources)
                if nested is not None and nested.path not in visited:
                    visited.add(nested.path)
                    current, _ = _header_urls(nested)
                    links.extend(current)
        unique = {row['url']: row for row in links}
        result['documentation_links'] = [unique[url] for url in sorted(unique)[:max_urls]]
        return dict(result, status='analyzed', matched_examples=len(ranked), selected_control_bytes=used,
                    original_source_sha256=hashlib.sha256(original_data).hexdigest(),
                    modified_source_sha256=hashlib.sha256(owner.data).hexdigest())
    except (SyntaxError, KeyError, ValueError, TypeError, AttributeError, RecursionError) as error:
        return dict(result, status='unknown_source_context', controls=[], documentation_links=[],
                    unknowns=[dict(reason='source_context_unavailable', detail=str(error))])
