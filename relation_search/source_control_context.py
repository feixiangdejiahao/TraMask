"""Recover bounded example tests through a changed call's source binding.

Only Python tests in the same complete source module are considered. This is
context retrieval, not oracle validation or a proof that two calls are
semantically equivalent. Production bodies and fetched documentation text are
never returned. Literal similarity ranks already binding-matched examples;
issue text, outcomes, labels and candidate identifiers play no part.
"""
from __future__ import annotations

import ast
from difflib import SequenceMatcher
import hashlib
import re


VERSION = 'same-binding-source-controls.v1'
POLICY = dict(
    scope='python module-level test_ functions in complete modified owner source',
    seeds='calls whose argument overlaps a non-oracle edit',
    identity='same unique fixture declaration and method; explicit imported API; local function declaration',
    ranking='fixture identity first, then maximum contiguous literal fragment length, then source order',
    literals='changed-call argument literals versus first 64 setup/call string/bytes literals, at most 256 characters each; docstrings/assert statements excluded',
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


def _span(node, path, offsets, decorated=False):
    first = min([node, *getattr(node, 'decorator_list', [])], key=lambda n: (n.lineno, n.col_offset)) if decorated else node
    start = offsets[first.lineno - 1] + first.col_offset
    if decorated and first is not node:
        start -= 1  # include the @ token preceding the decorator expression
    return dict(path=path, start_byte=start,
                end_byte=offsets[node.end_lineno - 1] + node.end_col_offset,
                line=first.lineno, end_line=node.end_lineno)


def _overlap(a, b):
    return a['path'] == b['path'] and a['start_byte'] < b['end_byte'] and b['start_byte'] < a['end_byte']


def _imports(tree):
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
    return {name: value for name, value in result.items() if name not in ambiguous | bindings}


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


def _literals(function):
    doc = function.body[0] if function.body and isinstance(function.body[0], ast.Expr) and isinstance(function.body[0].value, ast.Constant) and isinstance(function.body[0].value.value, str) else None
    assertion_nodes = {id(part) for check in _walk(function) if isinstance(check, ast.Assert)
                       for part in ast.walk(check)}
    values = []
    for statement in function.body:
        if statement is doc or isinstance(statement, ast.Assert):
            continue
        for node in _walk(statement):
            if id(node) in assertion_nodes:
                continue
            if isinstance(node, ast.Constant) and isinstance(node.value, (str, bytes)):
                value = node.value if isinstance(node.value, str) else node.value.decode('latin1')
                if 2 <= len(value) <= 256:
                    values.append(value)
                    if len(values) == 64:
                        return values
    return values


def _similarity(left, right):
    return max((SequenceMatcher(None, a, b, autojunk=False).find_longest_match().size
                for a in left for b in right), default=0)


def _identity(call, function, fixtures, imports, functions, path, offsets):
    parameters, assigned, stored = _names(function)
    parts = _chain(call.func)
    if not parts:
        return None
    if len(parts) == 2 and parts[0] in parameters and parts[0] in fixtures:
        if parts[0] in assigned or parts[0] in _parametrized(function):
            return None
        fixture = fixtures[parts[0]]
        position = _span(fixture, path, offsets)
        return dict(key=('fixture', path, position['start_byte'], parts[1]), kind='same_fixture_definition_and_method',
                    priority=1, fixture=fixture)
    imported = _import_symbol(call.func, imports, parameters | stored)
    if imported and imported[1]:
        return dict(key=('import', *imported), kind='same_explicit_import_binding', priority=0,
                    module=imported[0])
    if len(parts) == 1 and parts[0] not in parameters | stored and len(functions.get(parts[0], [])) == 1:
        declaration = functions[parts[0]][0]
        return dict(key=('local', path, _span(declaration, path, offsets)['start_byte']),
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
        links.append(dict(url=url, span=dict(path=source.path, start_byte=start, end_byte=start + len(url.encode())),
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
        sources, owner, changes, *_ = _modified_sources(corpus, candidate)
        tree = ast.parse(owner.code)
        offsets = _offsets(owner.code)
        functions = [n for n in tree.body if isinstance(n, _FUNCTIONS)]
        named = {}
        for function in functions:
            named.setdefault(function.name, []).append(function)
        selected = corpus['tests'][candidate['base_test_id']]
        definition = selected.get('definition_span', selected['span'])
        roots = [f for f in functions if _span(f, owner.path, offsets)['start_byte'] == definition['start_byte']]
        if len(roots) != 1:
            return dict(result, status='unknown_root_scope')
        root = roots[0]
        imports = _imports(tree)
        fixtures = _fixtures(functions, imports)
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
        root_literals = []
        for call, _ in seeds:
            for argument in [*call.args, *(keyword.value for keyword in call.keywords)]:
                for literal in _walk(argument):
                    if isinstance(literal, ast.Constant) and isinstance(literal.value, (str, bytes)):
                        value = literal.value if isinstance(literal.value, str) else literal.value.decode('latin1')
                        if 2 <= len(value) <= 256 and len(root_literals) < 64:
                            root_literals.append(value)
        ranked, modules = [], set()
        for function in functions:
            if function is root or not function.name.startswith('test_'):
                continue
            matches = []
            for call in _walk(function):
                if not isinstance(call, ast.Call):
                    continue
                identity = _identity(call, function, fixtures, imports, named, owner.path, offsets)
                if not identity:
                    continue
                for changed_call, seed in seeds:
                    if identity['key'] == seed['key']:
                        matches.append((changed_call, call, seed))
            if not matches:
                continue
            score = max(m[2]['priority'] for m in matches), _similarity(root_literals, _literals(function))
            position = _span(function, owner.path, offsets, decorated=True)
            code = owner.data[position['start_byte']:position['end_byte']].decode()
            records = []
            for changed_call, call, identity in matches:
                record = dict(identity=list(identity['key']), basis=identity['kind'],
                              changed_call=_span(changed_call, owner.path, offsets),
                              example_call=_span(call, owner.path, offsets), equivalence_proved=False)
                if 'fixture' in identity:
                    fixture = identity['fixture']
                    extent = _span(fixture, owner.path, offsets, decorated=True)
                    record['fixture'] = dict(span=extent, code=owner.data[extent['start_byte']:extent['end_byte']].decode())
                    returned = [n.value for n in _walk(fixture) if isinstance(n, ast.Return)]
                    if len(returned) == 1 and isinstance(returned[0], ast.Call):
                        symbol = _import_symbol(returned[0].func, imports, _names(fixture)[2])
                        if symbol:
                            modules.add(symbol[0])
                elif 'module' in identity:
                    modules.add(identity['module'])
                records.append(record)
            ranked.append((score, position['start_byte'], dict(name=function.name, span=position, code=code,
                matches=records, literal_fragment_score=score[1], oracle_validity='unconfirmed_source_example')))
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
        for module in sorted(modules):
            source = _module_source(module, sources)
            if source is None:
                continue
            current, children = _header_urls(source)
            links.extend(current)
            visited.add(source.path)
            for child in children:
                nested = _module_source(child, sources)
                if nested is not None and nested.path not in visited:
                    visited.add(nested.path)
                    current, _ = _header_urls(nested)
                    links.extend(current)
        unique = {row['url']: row for row in links}
        result['documentation_links'] = [unique[url] for url in sorted(unique)[:max_urls]]
        return dict(result, status='analyzed', matched_examples=len(ranked), selected_control_bytes=used,
                    source_sha256=hashlib.sha256(owner.data).hexdigest())
    except (SyntaxError, KeyError, ValueError, TypeError, AttributeError, RecursionError) as error:
        return dict(result, status='unknown_source_context', controls=[], documentation_links=[],
                    unknowns=[dict(reason='source_context_unavailable', detail=str(error))])
