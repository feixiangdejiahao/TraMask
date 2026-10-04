"""Check concrete positive keyboard inputs against a documented CSI domain.

This is a prerequisite gate, not an output oracle. It follows frozen source
bindings and public documentation. It never executes repository code. A checked
input does not establish the truth of any retained test assertion.
"""
from __future__ import annotations

import ast
from collections import defaultdict, deque
import hashlib
import itertools
import re

from combination_testing.protocol import Packet
from combination_testing.protocol_inputs import input_applicability

VERSION = 'source-bound-csi-input-domain.v1'
SPEC = 'https://sw.kovidgoyal.net/kitty/keyboard-protocol/'
UNKNOWN = object()
FIELDS = frozenset(('key', 'character', 'phase', 'modifiers', 'base_key',
                   'shifted_key', 'base_layout_key', 'aliases', 'is_press',
                   'is_repeat', 'is_release', 'shift', 'alt', 'ctrl', 'super',
                   'hyper', 'meta'))
POLICY = dict(version=VERSION,
    purpose='Check the input domain of normal positive key-decoding tests; retain whole-test P/Q review.',
    domain_binding='Imported fresh constructor, source-resolved consumer, structural class call path, public Kitty/CSI documentation and the public issue.',
    authority=SPEC,
    limitations=['Python and finite constant parameter rows only.',
                 'Class dispatch is a source inference, not a dynamic proof.',
                 'Split streams, prior nonempty feeds, uncertain helpers and exception contexts stay unknown.',
                 'Producer support limits do not establish a receiver rejection obligation.'],
    forbidden_inputs=['case IDs', 'candidate IDs', 'provider decisions', 'native results', 'audit labels'])


def _sha(text):
    return hashlib.sha256(text.encode()).hexdigest()


def _parse(code):
    try:
        return ast.parse(code)
    except (SyntaxError, ValueError, RecursionError):
        return None


def _receipt(code, node, path, *, role='source'):
    starts = [0]
    for line in code.encode().splitlines(keepends=True):
        starts.append(starts[-1] + len(line))
    start = starts[node.lineno - 1] + node.col_offset
    end = starts[node.end_lineno - 1] + node.end_col_offset
    return dict(path=path, source_sha256=_sha(code), start_byte=start, end_byte=end,
                text=code.encode()[start:end].decode(), role=role)


def _imports(tree):
    rows = defaultdict(set)
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            for item in node.names:
                rows[item.asname or item.name].add(node.module + '.' + item.name)
        elif isinstance(node, ast.Import):
            for item in node.names:
                rows[item.asname or item.name.split('.')[0]].add(item.name if item.asname else item.name.split('.')[0])
    overwritten = set()
    for node in tree.body:
        if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            overwritten.update(n.id for target in targets for n in ast.walk(target) if isinstance(n, ast.Name))
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            overwritten.add(node.name)
    return {key: next(iter(values)) for key, values in rows.items() if len(values) == 1 and key not in overwritten}


def _identity(node, imports):
    if isinstance(node, ast.Name):
        return imports.get(node.id)
    if isinstance(node, ast.Attribute):
        parent = _identity(node.value, imports)
        return parent + '.' + node.attr if parent else None
    return None


def _constant(node, env):
    """Bounded constants only; no calls, conversions or repository evaluation."""
    if isinstance(node, ast.Constant) and type(node.value) in (str, int, bool, type(None)):
        return node.value
    if isinstance(node, ast.Name):
        return env.get(node.id, UNKNOWN)
    if isinstance(node, (ast.Tuple, ast.List)) and len(node.elts) <= 128:
        values = [_constant(n, env) for n in node.elts]
        return values if all(v is not UNKNOWN for v in values) else UNKNOWN
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left, right = _constant(node.left, env), _constant(node.right, env)
        if type(left) is type(right) and type(left) in (str, int):
            result = left + right
            return result if not isinstance(result, str) or len(result) <= 16384 else UNKNOWN
    if isinstance(node, ast.JoinedStr):
        pieces = []
        for part in node.values:
            if isinstance(part, ast.Constant) and isinstance(part.value, str):
                pieces.append(part.value)
            elif isinstance(part, ast.FormattedValue) and part.conversion == -1 and part.format_spec is None:
                value = _constant(part.value, env)
                if type(value) not in (str, int):
                    return UNKNOWN
                pieces.append(str(value))
            else:
                return UNKNOWN
        return ''.join(pieces) if sum(map(len, pieces)) <= 16384 else UNKNOWN
    return UNKNOWN


def _frames(function, imports):
    groups = []
    for decorator in function.decorator_list:
        target = decorator.func if isinstance(decorator, ast.Call) else decorator
        identity = _identity(target, imports)
        if identity in ('pytest.mark.xfail', 'pytest.mark.skip', 'pytest.mark.skipif'):
            return None
        if identity == 'pytest.mark.parametrize' and isinstance(decorator, ast.Call) and len(decorator.args) >= 2:
            if any(k.arg == 'indirect' and _constant(k.value, {}) is not False for k in decorator.keywords):
                return None
            names, rows = (_constant(arg, {}) for arg in decorator.args[:2])
            if isinstance(names, str):
                names = [name.strip() for name in names.split(',')]
            if not isinstance(names, list) or not all(isinstance(n, str) for n in names) or not isinstance(rows, list):
                return None
            group = []
            for row in rows:
                values = [row] if len(names) == 1 else row
                if not isinstance(values, list) or len(values) != len(names):
                    return None
                group.append(dict(zip(names, values)))
            groups.append(group)
        elif isinstance(target, ast.Attribute) and target.attr == 'parametrize':
            return None
    size = 1
    for group in groups:
        size *= len(group)
    if size > 128:
        return None
    return [dict(item for group in row for item in group.items()) for row in itertools.product(*groups)]


def _fragments(payload, analysis):
    if analysis and 'sources' in analysis:
        return [(row['path'], row['code']) for row in analysis['sources'].values()]
    pattern = r'^S\d+ (.+?) bytes \d+:\d+\n```\n(.*?)\n```'
    return re.findall(pattern, payload.get('source_analysis', ''), re.M | re.S)


def _source_rows(sources):
    result = {}
    for path, value in (sources or {}).items():
        code = value if isinstance(value, str) else value.get('code')
        # Histories may supply extra test helpers, but domain contracts must be repository source.
        if isinstance(code, str) and (isinstance(value, str) or value.get('origin', 'repository') == 'repository'):
            result[path] = code
    return result


def _scope_nodes(node):
    """Visit the current method, excluding bodies of uncalled nested definitions."""
    yield node
    for child in ast.iter_child_nodes(node):
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
            continue
        if isinstance(child, ast.If) and isinstance(child.test, ast.Constant):
            for statement in child.body if child.test.value else child.orelse:
                yield from _scope_nodes(statement)
        else:
            yield from _scope_nodes(child)


class _Domain:
    def __init__(self, sources, issue):
        self.sources, self.issue, self.classes = sources, issue, {}

    def load(self, qualified):
        if qualified in self.classes:
            return self.classes[qualified]
        self.classes[qualified] = None
        module, _, name = qualified.rpartition('.')
        paths = [p for p in self.sources if p in (module.replace('.', '/') + '.py', 'src/' + module.replace('.', '/') + '.py')]
        if len(paths) != 1:
            return None
        path = paths[0]; code = self.sources[path]; tree = _parse(code)
        if tree is None:
            return None
        nodes = [n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == name]
        if len(nodes) != 1:
            return None
        node = nodes[0]; imports = _imports(tree)
        methods = {n.name: n for n in node.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
        bases = []
        for base in node.bases:
            base = base.value if isinstance(base, ast.Subscript) else base
            identity = _identity(base, imports)
            if identity and self.load(identity):
                bases.append(identity)
        value = dict(qualified=qualified, node=node, path=path, code=code, methods=methods, bases=bases)
        self.classes[qualified] = value
        return value

    def method(self, cls, name, seen=()):
        if cls in seen or not (row := self.load(cls)):
            return None
        if name in row['methods']:
            return cls, name
        found = [self.method(base, name, (*seen, cls)) for base in row['bases']]
        found = [item for item in found if item]
        return found[0] if len(found) == 1 else None

    def bind(self, cls, consumer):
        if not re.search(r'kitty\s+keyboard\s+protocol', self.issue, re.I):
            return None, 'public_issue_does_not_identify_keyboard_domain'
        root = self.method(cls, consumer)
        if root is None:
            return None, 'consumer_declaration_unresolved'
        classes, pending = {}, [cls]
        while pending:
            name = pending.pop()
            if name in classes or not (row := self.load(name)):
                continue
            classes[name] = row; pending.extend(row['bases'])
        # Generator/callback state connects a public feed method to an overridden parser.
        stored = defaultdict(set)
        methods = {(name, method): node for name, row in classes.items() for method, node in row['methods'].items()}
        for (owner, _), node in methods.items():
            for item in _scope_nodes(node):
                if not isinstance(item, ast.Assign) or not isinstance(item.value, ast.Call):
                    continue
                fn = item.value.func
                if isinstance(fn, ast.Attribute) and isinstance(fn.value, ast.Name) and fn.value.id == 'self':
                    destination = self.method(cls, fn.attr)
                    for target in item.targets:
                        if isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name) and target.value.id == 'self' and destination:
                            stored[target.attr].add(destination)
        edges = defaultdict(list); docs = {}
        for key, node in methods.items():
            row = classes[key[0]]; aliases = {}
            for item in _scope_nodes(node):
                if isinstance(item, ast.Assign) and len(item.targets) == 1 and isinstance(item.targets[0], ast.Name):
                    if isinstance(item.value, ast.Attribute) and isinstance(item.value.value, ast.Name) and item.value.value.id == 'self':
                        aliases[item.targets[0].id] = item.value.attr
                if not isinstance(item, ast.Call):
                    continue
                fn = item.func; destination = None
                if isinstance(fn, ast.Name) and fn.id in aliases:
                    destination = self.method(cls, aliases[fn.id])
                elif isinstance(fn, ast.Attribute):
                    if isinstance(fn.value, ast.Name) and fn.value.id == 'self':
                        destination = self.method(cls, fn.attr)
                    elif isinstance(fn.value, ast.Call) and isinstance(fn.value.func, ast.Name) and fn.value.func.id == 'super' and not fn.value.args:
                        targets = [self.method(base, fn.attr) for base in row['bases']]
                        targets = [target for target in targets if target]
                        destination = targets[0] if len(targets) == 1 else None
                    elif isinstance(fn.value, ast.Attribute) and isinstance(fn.value.value, ast.Name) and fn.value.value.id == 'self':
                        targets = stored.get(fn.value.attr, set())
                        destination = next(iter(targets)) if len(targets) == 1 and fn.attr in ('send', 'throw', '__next__') else None
                if destination:
                    edges[key].append((destination, _receipt(row['code'], item, row['path'])))
            doc = ast.get_docstring(node, clean=False) or ''
            if re.search(r'kitty\s+keyboard\s+protocol', doc, re.I) and 'CSI' in doc:
                docs[key] = _receipt(row['code'], node.body[0], row['path'], role='public_documentation')
        queue = deque([(root, [])]); seen = set()
        while queue:
            key, trail = queue.popleft()
            if key in seen:
                continue
            seen.add(key)
            if key in docs:
                row = classes[root[0]]; node = row['methods'][root[1]]
                header = _receipt(row['code'], node, row['path'], role='consumer_declaration')
                first = node.body[0]
                # Keep only the declaration header; implementation values are not contract evidence.
                stop = _receipt(row['code'], first, row['path'])['start_byte']
                header['end_byte'] = stop; header['text'] = row['code'].encode()[header['start_byte']:stop].decode()
                return dict(consumer=cls + '.' + consumer, declaration=header,
                    public_documentation=docs[key], structural_call_path=trail,
                    association='source_bound_class_dispatch_inference',
                    issue_receipt=dict(path='<issue>', source_sha256=_sha(self.issue), start_byte=0,
                        end_byte=len(self.issue.encode()), text=self.issue)), None
            for destination, receipt in edges[key]:
                queue.append((destination, trail + [dict(caller='.'.join(key), callee='.'.join(destination), receipt=receipt)]))
        return None, 'no_class_call_path_to_public_protocol_documentation'


def _wire(value):
    if not isinstance(value, str) or not value.startswith('\x1b['):
        return None, [], []
    packet = Packet.parse(value)
    if packet is None or not re.fullmatch(r'\x1b\[[0-9]+(?::[0-9]*){0,2}(?:;[0-9]*(?::[0-9]+)?)?(?:;[0-9]+(?::[0-9]+)*)?[u~ABCDEFHPQS]', value):
        return None, [], ['packet_or_stream_boundary_unresolved']
    check = input_applicability(packet.as_dict())
    violations = [r for r in check['reasons'] if r != 'functional_alternates_outside_producer_domain']
    unknown = [r for r in check['reasons'] if r == 'functional_alternates_outside_producer_domain']
    if packet.key.endswith('u') and 65 <= int(packet.key[:-1]) <= 90:
        violations.append('ascii_uppercase_primary_is_not_unshifted')
    return packet.as_dict(), violations, unknown


def analyze(payload, *, analysis=None, sources=None):
    """Return allow/reject/unknown, with byte-bound evidence and no oracle repair.

    ``analysis`` is the optional frozen finite source graph. ``sources`` maps
    repository paths to code or corpus source records. IDs/outcomes are ignored.
    ``allow`` only means that this bounded gate found no blocking obligation.
    """
    result = dict(version=VERSION, decision='allow', status='outside_registered_scope',
                  allow_prior_gate=True, checks=[], unknowns=[], authority=SPEC,
                  original_test_sha256=_sha(payload.get('original_test', '')),
                  modified_test_sha256=_sha(payload.get('modified_test', '')),
                  whole_test_semantics='unconfirmed')
    if payload.get('language') != 'python':
        return result
    code = payload.get('modified_test', ''); tree = _parse(code)
    if tree is None:
        result['unknowns'].append('complete_test_syntax_unresolved')
    else:
        roots = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
        if len(roots) != 1:
            result['unknowns'].append('complete_test_root_unresolved')
        else:
            _inspect(payload, roots[0], code, analysis, _source_rows(sources), result)
    if any(row['decision'] == 'reject' for row in result['checks']):
        result.update(decision='reject', status='positive_keyboard_input_contradicts_domain', allow_prior_gate=False)
    elif result['unknowns'] or any(row['decision'] == 'unknown' for row in result['checks']):
        result.update(decision='unknown', status='input_domain_or_binding_unproved', allow_prior_gate=False)
    elif result['checks']:
        result['status'] = 'bounded_input_domain_checked'
    return result


def _inspect(payload, root, code, analysis, sources, result):
    fragments = _fragments(payload, analysis); imports = {}; definitions = defaultdict(list)
    root_paths = {path for path, fragment in fragments if code == fragment or code in fragment}
    if not root_paths and len({path for path, _ in fragments}) == 1:
        root_paths = {fragments[0][0]}
    root_path = next(iter(root_paths)) if len(root_paths) == 1 else None
    called_names = {n.func.id for n in ast.walk(root) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    for path, fragment in fragments:
        if path != root_path or path not in sources or fragment not in sources[path]:
            parsed = _parse(fragment)
            if parsed and fragment != code and any(isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and n.name in called_names and _may_feed(n) for n in parsed.body):
                result['unknowns'].append('helper_source_or_scope_not_verified')
            continue
        parsed = _parse(fragment)
        if parsed is None:
            continue
        for key, value in _imports(parsed).items():
            if key in imports and imports[key] != value:
                imports[key] = None
            else:
                imports[key] = value
        for node in parsed.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name != root.name:
                definitions[node.name].append((node, fragment, path))
    if root_path in sources and (module_tree := _parse(sources[root_path])) is not None:
        # A later source assignment can overwrite an imported constructor alias.
        imports = _imports(module_tree)
    imports = {key: value for key, value in imports.items() if value}
    fixtures = {}
    for arg in root.args.args:
        rows = definitions.get(arg.arg, [])
        if len(rows) != 1:
            continue
        node, fragment, path = rows[0]
        decorated = any(_identity(d.func if isinstance(d, ast.Call) else d, imports) == 'pytest.fixture' for d in node.decorator_list)
        body = [n for n in node.body if not (isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant) and isinstance(n.value.value, str))]
        if decorated and len(body) == 1 and isinstance(body[0], ast.Return) and isinstance(body[0].value, ast.Call):
            call = body[0].value; identity = _identity(call.func, imports)
            if identity and not call.args and not call.keywords:
                fixtures[arg.arg] = dict(identity=identity, fixture=_receipt(fragment, node, path, role='fixture'))
    frames = _frames(root, imports)
    if frames is None:
        if '\\x1b[' in code or '\x1b[' in code:
            result['unknowns'].append('parameter_rows_or_test_mark_unresolved')
        return
    domain = _Domain(sources, payload.get('issue', ''))
    for frame in frames:
        _scan_body(root.body, dict(frame), {k: v for k, v in fixtures.items() if k not in frame}, code, '<modified_test>',
                   definitions, domain, result, frame, [], {}, depth=0)


def _positive_name(target, following):
    if not isinstance(target, (ast.Tuple, ast.List)) or len(target.elts) != 1 or not isinstance(target.elts[0], ast.Name):
        return None
    name = target.elts[0].id
    for stmt in following:
        if any(isinstance(n, ast.Name) and n.id == name and isinstance(n.ctx, (ast.Store, ast.Del)) for n in ast.walk(stmt)):
            return None
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and stmt.name == name:
            return None
        if isinstance(stmt, ast.Assert):
            test = stmt.test
            operands = [test.left, *test.comparators] if isinstance(test, ast.Compare) else [test]
            if any(isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name)
                   and n.value.id == name and n.attr in FIELDS for n in operands):
                return name
        # A call receiving the result can change it before the supposed positive check.
        if any(isinstance(n, ast.Call) and any(isinstance(v, ast.Name) and v.id == name for v in ast.walk(n)) for n in ast.walk(stmt)):
            return None
        # Do not search callbacks, nested classes or a different object for evidence.
        if isinstance(stmt, (ast.Return, ast.Raise, ast.Try, ast.With, ast.AsyncWith, ast.If, ast.For)):
            break
    return None


def _collecting_helper(helper):
    """Recognize a returned list built only from feed iterations and a type filter."""
    body = [n for n in helper.body if not (isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant) and isinstance(n.value.value, str))]
    if len(body) < 3 or not isinstance(body[0], ast.Assign) or len(body[0].targets) != 1:
        return False
    target = body[0].targets[0]
    if not isinstance(target, ast.Name) or not isinstance(body[0].value, ast.List) or body[0].value.elts:
        return False
    collector = target.id
    for stmt in body[1:-1]:
        if not isinstance(stmt, ast.For) or stmt.orelse or not isinstance(stmt.target, ast.Name) or len(stmt.body) != 1:
            return False
        if not isinstance(stmt.iter, ast.Call) or not isinstance(stmt.iter.func, ast.Attribute) or stmt.iter.func.attr != 'feed':
            return False
        item = stmt.body[0]
        if not isinstance(item, ast.Expr) or not isinstance(item.value, ast.Call):
            return False
        call = item.value
        if not (isinstance(call.func, ast.Attribute) and isinstance(call.func.value, ast.Name)
                and call.func.value.id == collector and call.func.attr == 'append'
                and len(call.args) == 1 and isinstance(call.args[0], ast.Name)
                and call.args[0].id == stmt.target.id and not call.keywords):
            return False
    if not isinstance(body[-1], ast.Return):
        return False
    value = body[-1].value
    if isinstance(value, ast.Name):
        return value.id == collector
    if not isinstance(value, ast.ListComp) or len(value.generators) != 1:
        return False
    gen = value.generators[0]
    if not (isinstance(gen.iter, ast.Name) and gen.iter.id == collector and isinstance(gen.target, ast.Name)
            and isinstance(value.elt, ast.Name) and value.elt.id == gen.target.id and not gen.is_async):
        return False
    return all(isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == 'isinstance'
               and len(n.args) == 2 and isinstance(n.args[0], ast.Name) and n.args[0].id == gen.target.id
               and isinstance(n.args[1], (ast.Name, ast.Attribute)) and not n.keywords for n in gen.ifs)


def _may_feed(node):
    return any(isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == 'feed' for n in ast.walk(node))


def _scan_body(body, env, objects, code, path, definitions, domain, result, frame, chain, feeds, *, depth, positive=False):
    shadowed = set()
    for index, stmt in enumerate(body):
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            shadowed.add(stmt.name)
            continue
        if isinstance(stmt, (ast.Return, ast.Raise)):
            return
        if isinstance(stmt, ast.Assert):
            truth = _constant(stmt.test, env)
            if truth is UNKNOWN:
                if any(_may_feed(n) or any(isinstance(c, ast.Call) and isinstance(c.func, ast.Name) and c.func.id in definitions and any(_may_feed(h[0]) for h in definitions[c.func.id]) for c in ast.walk(n)) for n in body[index + 1:]):
                    result['unknowns'].append('prior_assertion_reachability_unresolved')
                return
            if not truth:
                return
            continue
        if isinstance(stmt, (ast.Try, ast.With, ast.AsyncWith, ast.If, ast.While)):
            if _may_feed(stmt):
                result['unknowns'].append('conditional_or_exception_consumer_not_positive')
                objects.clear()
            elif any(isinstance(n, ast.Name) and n.id in objects for n in ast.walk(stmt)):
                objects.clear()
            continue
        call = stmt.value if isinstance(stmt, (ast.Assign, ast.AnnAssign, ast.Expr)) else stmt.iter if isinstance(stmt, ast.For) else None
        target = stmt.targets[0] if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1 else stmt.target if isinstance(stmt, ast.AnnAssign) else None
        local_positive = positive or bool(_positive_name(target, body[index + 1:]))
        if isinstance(call, ast.Call):
            if isinstance(call.func, ast.Attribute) and call.func.attr == 'feed':
                receiver = objects.get(call.func.value.id) if isinstance(call.func.value, ast.Name) else None
                value = _constant(call.args[0], env) if len(call.args) == 1 and not call.keywords else UNKNOWN
                if value == '':
                    continue
                possible = value is UNKNOWN or isinstance(value, str) and value.startswith('\x1b[')
                if receiver:
                    identity = receiver['identity']; previous = feeds.get(identity, 0); feeds[identity] = previous + 1
                else:
                    identity = None; previous = 0
                if possible:
                    row = dict(value=None if value is UNKNOWN else value, parameter_frame=frame,
                        call_receipt=_receipt(code, call, path), binding_chain=chain,
                        positive_key_result=local_positive, decision='unknown', violations=[], unknowns=[])
                    result['checks'].append(row)
                    if not local_positive:
                        row['unknowns'].append('normal_positive_key_result_not_established')
                    elif receiver is None:
                        row['unknowns'].append('receiver_fixture_binding_unresolved')
                    elif previous:
                        row['unknowns'].append('prior_stream_state_unresolved')
                    elif value is UNKNOWN:
                        row['unknowns'].append('concrete_input_unresolved')
                    else:
                        evidence, reason = domain.bind(identity, call.func.attr)
                        if evidence is None:
                            row['unknowns'].append(reason)
                        else:
                            row.update(domain_binding=evidence, fixture_receipt=receiver['fixture'])
                            packet, violations, unknown = _wire(value)
                            row.update(packet=packet, violations=violations, unknowns=unknown,
                                decision='reject' if violations else 'unknown' if unknown else 'allow')
            elif isinstance(call.func, ast.Name) and call.func.id in definitions and depth < 3:
                options = definitions[call.func.id]
                if call.func.id in shadowed:
                    result['unknowns'].append('helper_shadowed_in_local_scope'); continue
                if len(options) != 1:
                    result['unknowns'].append('helper_declaration_ambiguous'); continue
                helper, helper_code, helper_path = options[0]
                if not _collecting_helper(helper):
                    if _may_feed(helper):
                        result['unknowns'].append('helper_output_to_consumer_flow_unproved')
                    continue
                params = helper.args.posonlyargs + helper.args.args
                if call.keywords or len(call.args) != len(params):
                    if any(isinstance(n, ast.Constant) and isinstance(n.value, str) and '\x1b[' in n.value for n in ast.walk(call)):
                        result['unknowns'].append('helper_argument_binding_unresolved')
                    continue
                values = {}; receivers = {}; bindings = []
                for parameter, argument in zip(params, call.args):
                    value = _constant(argument, env)
                    if value is not UNKNOWN:
                        values[parameter.arg] = value
                    if isinstance(argument, ast.Name) and argument.id in objects:
                        receivers[parameter.arg] = objects[argument.id]
                    bindings.append(dict(formal=parameter.arg, actual=_receipt(code, argument, path)))
                _scan_body(helper.body, values, receivers, helper_code, helper_path, definitions,
                    domain, result, frame, chain + [dict(call=_receipt(code, call, path), arguments=bindings)],
                    feeds, depth=depth + 1, positive=local_positive)
            else:
                if _may_feed(call):
                    result['unknowns'].append('wrapped_consumer_flow_unresolved')
                # Unknown calls can mutate a supplied receiver or replace its feed method.
                for name in {n.id for n in ast.walk(call) if isinstance(n, ast.Name)} & objects.keys():
                    objects.pop(name, None)
        if isinstance(stmt, (ast.Assign, ast.AnnAssign)):
            targets = stmt.targets if isinstance(stmt, ast.Assign) else [stmt.target]
            value = _constant(stmt.value, env)
            for target in targets:
                if isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name):
                    objects.pop(target.value.id, None)
                if isinstance(target, ast.Name):
                    shadowed.add(target.id)
                    env.pop(target.id, None); objects.pop(target.id, None)
                    if value is not UNKNOWN:
                        env[target.id] = value
        if isinstance(stmt, ast.For) and any(_may_feed(n) for n in stmt.body):
            result['unknowns'].append('loop_consumer_reachability_unresolved')
