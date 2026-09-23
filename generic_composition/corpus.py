"""Source-backed assertion capsules and donors, without subject API rules.

Only test discovery/assertion conventions differ between languages. Calls in the
program under test are opaque symbols. Source bytes, not reconstructed code, are
the editing authority. Flow facts are explicitly may-dependence information;
they are never presented as a proof that an oracle can be transplanted.
"""
from __future__ import annotations

import collections
import hashlib
import json
import posixpath
from pathlib import Path
from typing import Any, Iterable

from anchor_retrieval.frontier import observation_expression
from anchor_retrieval.index import Index
from anchor_retrieval.syntax import (
    ATTRS, CALLS, FUNCTIONS, IDENTIFIERS, SKIP, Source, Unit, attr_parts,
    call_parts, child, is_test_path, json_safe, literal, walk,
)


LITERALS = {
    'string', 'raw_string_literal', 'interpreted_string_literal', 'integer',
    'float', 'int_literal', 'float_literal', 'number', 'true', 'false', 'none',
    'nil', 'null', 'undefined', 'template_string',
}
ASSIGNMENTS = {
    'assignment', 'assignment_statement', 'short_var_declaration',
    'variable_declarator', 'named_expression', 'augmented_assignment',
    'var_spec', 'const_spec',
}
CONTAINERS = {'dictionary', 'list', 'tuple', 'array', 'object', 'composite_literal'}


def span(source: Source, node) -> dict | None:
    if node is None:
        return None
    return {'path': source.path, 'start_byte': node.start_byte,
            'end_byte': node.end_byte, 'line': node.start_point.row + 1,
            'end_line': node.end_point.row + 1}


def _id(*parts: Any) -> str:
    return hashlib.sha256(json.dumps(parts, sort_keys=True, ensure_ascii=True).encode()).hexdigest()[:24]


def ast_tree(source: Source, node) -> dict | None:
    """Source-spanned token tree; punctuation/fields stay, gaps use source bytes."""
    if node is None:
        return None
    result = {'kind': node.type, 'is_named': node.is_named,
              'start_byte': node.start_byte, 'end_byte': node.end_byte}
    if not node.children:
        result['text'] = source.text(node)
    else:
        result['children'] = [dict(ast_tree(source, n), field=node.field_name_for_child(i))
                              for i, n in enumerate(node.children)]
    return result


def _contains(outer, inner) -> bool:
    return outer is not None and inner is not None and outer.start_byte <= inner.start_byte and inner.end_byte <= outer.end_byte


def _identifier_reads(source: Source, node) -> set[str]:
    result = set()
    if node is None:
        return result
    for n in walk(node):
        if n.type != 'identifier':
            continue
        p = n.parent
        if p is not None and p.type in ATTRS and n == attr_parts(p)[1]:
            continue
        if p is not None and p.type in {'pair', 'keyed_element'} and n == child(p, 'key'):
            continue
        result.add(source.text(n))
    return result


def _local_binders(source: Source, node) -> set[str]:
    names = set()
    for n in walk(node):
        if n.type in ASSIGNMENTS:
            target = child(n, 'left', 'name')
            if target is not None:
                names.update(source.text(x) for x in walk(target) if x.type == 'identifier')
        if n.type in FUNCTIONS | {'arrow_function', 'function_expression', 'func_literal', 'lambda'}:
            params = child(n, 'parameters', 'parameter')
            if params is not None:
                names.update(source.text(x) for x in walk(params) if x.type == 'identifier')
    return names


def expression(source: Source, node) -> dict | None:
    if node is None:
        return None
    result = {'text': source.text(node), 'kind': node.type, 'language': source.language, 'span': span(source, node),
              'ast': ast_tree(source, node),
              'free_identifiers': sorted(_identifier_reads(source, node) - _local_binders(source, node))}
    try:
        result['literal_value'] = json_safe(literal(result['text']))
        result['literal_known'] = True
    except ValueError:
        result['literal_known'] = False
    if node.type in {'raw_string_literal', 'interpreted_string_literal', 'string', 'template_string'}:
        result['embedded_language'] = 'opaque'
    return result


def _matching_node(source: Source, text: str, within=None, before: int | None = None):
    if not text:
        return None
    matches = [n for n in walk(within or source.root)
               if source.text(n) == text and (before is None or n.end_byte <= before)]
    return min(matches, key=lambda n: (n.end_byte - n.start_byte, n.start_byte)) if matches else None


def _value_definition(source: Source, name: str, before: int, within=None):
    """Nearest syntactic definition; callers label this resolution conservative."""
    found = []
    for n in walk(within or source.root):
        if n.type in ASSIGNMENTS and n.end_byte <= before:
            left, right = child(n, 'left', 'name'), child(n, 'right', 'value')
            if left is not None and source.text(left) == name and right is not None:
                if right.type == 'expression_list' and len(right.named_children) == 1:
                    right = right.named_children[0]
                found.append((n.end_byte, right))
    return max(found, key=lambda item: item[0])[1] if found else None


def _children_projections(source: Source, node):
    if node.type == 'composite_literal':
        body = child(node, 'body')
        if body is None:
            return
        node = body
    if node.type in {'dictionary', 'object', 'literal_value'}:
        for i, entry in enumerate(node.named_children):
            if entry.type == 'comment':
                continue
            if entry.type in {'pair', 'keyed_element'}:
                key, value = child(entry, 'key'), child(entry, 'value')
                if key is None or value is None:
                    continue
                if key.type == 'literal_element' and len(key.named_children) == 1:
                    key = key.named_children[0]
                if value.type == 'literal_element' and len(value.named_children) == 1:
                    value = value.named_children[0]
                try:
                    keyvalue = literal(source.text(key))
                except ValueError:
                    if source.language == 'typescript' and key.type in IDENTIFIERS:
                        keyvalue = source.text(key)
                    elif source.language == 'go' and key.type == 'identifier':
                        # A struct field and a dynamic map key cannot be distinguished here.
                        continue
                    else:
                        continue
                yield keyvalue, value
            elif node.type == 'literal_value' and entry.type == 'literal_element':
                yield i, entry.named_children[0] if len(entry.named_children) == 1 else entry
            elif node.type == 'object' and entry.type == 'shorthand_property_identifier':
                yield source.text(entry), entry
    elif node.type in {'list', 'tuple', 'array'}:
        for i, item in enumerate(n for n in node.named_children if n.type != 'comment'):
            if 'spread' not in item.type and 'splat' not in item.type:
                yield i, item


def expected_atoms(source: Source, node, *, before: int | None = None, within=None) -> list[dict]:
    """Decompose explicit expected containers; unknown calls remain whole atoms.

    Atoms describe projections, not executable assertions or automatically valid
    replacement oracles. Aliased identifier expansion carries its source binding.
    """
    result = []

    def visit(current, path, bindings, seen):
        if current is None:
            return
        if current.type == 'identifier' and source.text(current) not in seen:
            name = source.text(current)
            definition = _value_definition(source, name, before or current.start_byte, within)
            if definition is not None and definition.type in CONTAINERS:
                visit(definition, path, bindings + [{'name': name, 'span': span(source, definition),
                                                   'resolution': 'nearest_syntactic_definition'}], seen | {name})
                return
        pieces = list(_children_projections(source, current))
        if pieces:
            for key, value in pieces:
                visit(value, path + [json_safe(key)], bindings, seen)
        else:
            result.append({'projection': path, 'expected': expression(source, current),
                           'bindings': bindings})

    visit(node, [], [], set())
    return result


def _assertion_nodes(source: Source, assertion, unit: Unit):
    statements = [n for n in walk(unit.body) if n.start_point.row + 1 == assertion.line
                  and source.text(n) == assertion.text]
    statement = min(statements, key=lambda n: (n.type not in CALLS | {'assert_statement'},
                                              n.end_byte - n.start_byte)) if statements else None
    observed, expected_text = observation_expression(assertion, source)
    expected = None
    if source.language == 'python' and assertion.expression_node.type == 'comparison_operator':
        sides = assertion.expression_node.named_children
        if len(sides) == 2 and expected_text:
            expected = sides[0] if observed == sides[1] else sides[1]
    elif statement is not None and statement.type in CALLS:
        fn, args = call_parts(statement)
        if source.language == 'typescript' and len(args) == 1 and expected_text:
            expected = args[0]
        elif source.language == 'python' and len(args) > 1 and expected_text:
            expected = args[1]
        elif source.language == 'go' and assertion.predicate != 'assertion_helper' and len(args) >= 3 and expected_text:
            expected = args[1] if observed == args[2] else args[2]
    predicate = assertion.predicate
    if source.language == 'python' and assertion.expression_node.type == 'comparison_operator':
        node = assertion.expression_node
        predicate = ' '.join(source.text(n) for n in node.children if not n.is_named)
    return statement, observed, expected, predicate


def _call_context(source: Source, node, boundary=None) -> dict | None:
    current = node.parent
    while current is not None and current != boundary:
        if current.type in CALLS:
            fn, args = call_parts(current)
            for i, arg in enumerate(args):
                if _contains(arg, node):
                    keyword = source.text(child(arg, 'name')) if arg.type == 'keyword_argument' else None
                    return {'callee': source.text(fn), 'argument_slot': i, 'keyword': keyword,
                            'call_span': span(source, current), 'argument_span': span(source, arg)}
        current = current.parent
    return None


def _callee_identity(index: Index, unit: Unit, node, flow_call=None) -> dict:
    source = unit.source
    fn, _ = call_parts(node)
    name = source.text(fn)
    parts = name.split('.')
    imported = source.imports.get(parts[0])
    if imported:
        module, symbol = imported
        if source.language == 'typescript' and module.startswith('.'):
            module = posixpath.normpath(posixpath.join(posixpath.dirname(source.path), module))
        elif source.language == 'python' and module.startswith('.'):
            count = len(module) - len(module.lstrip('.'))
            parent = posixpath.dirname(source.path)
            for _ in range(count - 1):
                parent = posixpath.dirname(parent)
            module = posixpath.normpath(posixpath.join(parent, module[count:].replace('.', '/')))
        tail = '.'.join(([symbol] if symbol else []) + parts[1:])
        return {'canonical': module + '::' + tail, 'resolution': 'import_alias', 'display': name}
    targets = [(uid, reason) for uid, reason in (flow_call.targets if flow_call else index.resolve(unit, name))
               if reason in {'local_symbol', 'package_symbol', 'import_symbol'}]
    if len(targets) == 1:
        target = index.units[targets[0][0]]
        return {'canonical': target.source.path + '::' + target.owner + '.' + target.name,
                'resolution': targets[0][1], 'display': name}
    if len(parts) == 1 and source.language == 'go' and fn is not None and fn.type == 'identifier':
        return {'canonical': 'go-package:' + index.go_packages.get(source.path, '') + '::' + name,
                'resolution': 'package_unresolved_symbol', 'display': name}
    if len(parts) > 1 and parts[0] in unit.params:
        fixtures = index.local_functions(unit, parts[0], fixture=True)
        if len(fixtures) == 1:
            fixture = fixtures[0]
            return {'canonical': fixture.source.path + '::fixture:' + fixture.name + '.' + '.'.join(parts[1:]),
                    'resolution': 'fixture_binding', 'display': name}
    return {'canonical': None, 'resolution': 'unknown_receiver_or_symbol', 'display': name,
            'scope_key': source.path + '::' + name}


def _call_record(source: Source, node, identity=None) -> dict:
    fn, args = call_parts(node)
    return {'callee': source.text(fn), 'span': span(source, node),
            'callee_identity': identity or {'canonical': None, 'resolution': 'unknown'},
            'arguments': [dict(expression(source, a), slot=i) for i, a in enumerate(args)]}


def _input_provenance(index: Index, unit: Unit, flow, call_nodes: dict) -> tuple[dict, dict]:
    """Index value dependencies once: expression-span -> observed call slots."""
    slots = collections.defaultdict(list)
    call_records = {}
    for call in flow.calls:
        graph_node = flow.nodes[call.node]
        key = (graph_node['start_byte'], graph_node['end_byte'])
        node = call_nodes.get(key)
        if node is None:
            continue
        identity = _callee_identity(index, unit, node, call)
        call_records[key] = _call_record(unit.source, node, identity)
        _, source_args = call_parts(node)
        positional = iter(call.args)
        for slot, argument in enumerate(source_args):
            keyword = unit.source.text(child(argument, 'name')) if argument.type == 'keyword_argument' else None
            value = call.keywords.get(keyword) if keyword is not None else next(positional, None)
            if value is None:
                continue
            record = {'callee': call.name, 'callee_identity': identity, 'argument_slot': slot,
                      'keyword': keyword, 'call_span': span(unit.source, node),
                      'argument_span': span(unit.source, argument), 'dependence': 'local_may_value_flow'}
            for nid in flow.slice([value.id]):
                item = flow.nodes[nid]
                span_key = (item['start_byte'], item['end_byte'])
                if record not in slots[span_key]:
                    slots[span_key].append(record)
    return slots, call_records


def _support(index: Index, unit: Unit, flow) -> dict:
    helpers = {}
    for call in flow.calls:
        for uid, reason in call.targets:
            if reason in {'local_symbol', 'package_symbol', 'import_symbol', 'fixture'}:
                target = index.units[uid]
                if not target.test:
                    helpers[uid] = {'id': uid, 'name': target.name, 'span': span(target.source, target.node),
                                    'resolution': reason, 'oracle_helper': uid in index.oracle_helpers}
    fixtures = []
    for name in unit.params:
        found = index.local_functions(unit, name, fixture=True)
        fixtures.append({'name': name, 'sources': [span(u.source, u.node) for u in found],
                         'resolution': 'source_found' if found else 'parameter_or_external_fixture_unknown'})
    imports = [{'name': name, 'module': pair[0], 'imported_name': pair[1]}
               for name, pair in sorted(unit.source.imports.items())]
    return {'imports': imports, 'helpers': list(helpers.values()), 'fixtures': fixtures}


def _binding_facts(flow, sliced: set[int]) -> dict:
    nodes = [flow.nodes[i] for i in sorted(sliced)]
    return {
        'analysis': 'local_may_dependence',
        'reads': sorted({n.get('variable', n['text']) for n in nodes if n['kind'] in {'read', 'global', 'field_read'}}),
        'writes': sorted({n.get('variable', n['text']) for n in nodes if n['kind'] in {'definition', 'update', 'may_effect'}}),
        'unknown_effects': sorted({n['call'] for n in nodes if n['kind'] == 'call'}),
        'alias_precision': 'unknown',
        'closure_binding_precision': 'unknown',
        'slice_nodes': nodes,
        'slice_edges': [{'from': a, 'to': b, 'kind': flow.edge_kinds.get((a, b), 'value')}
                        for a in sorted(sliced) for b in sorted(flow.edges.get(a, ())) if b in sliced],
    }


def _oracle_value_spans(source: Source, node, flow, unit: Unit) -> list[dict]:
    """Track an expected argument back to its caller-side value definitions."""
    if node is None:
        return []
    nodes, seen = [node], set()
    result = []
    while nodes:
        current = nodes.pop()
        key = (current.start_byte, current.end_byte)
        if key in seen:
            continue
        seen.add(key)
        result.append(span(source, current))
        roots = [n['id'] for n in flow.nodes if (n['start_byte'], n['end_byte']) == key]
        for nid in flow.slice(roots):
            n = flow.nodes[nid]
            result.append({'path': source.path, 'start_byte': n['start_byte'], 'end_byte': n['end_byte']})
        # Frameworks usually do not evaluate expected arguments in Flow. A
        # syntactic definition link covers that boundary without executing it.
        for name in _identifier_reads(source, current):
            definition = _value_definition(source, name, current.start_byte, unit.body)
            if definition is not None:
                nodes.append(definition)
    return result


def _observation_value_trace(source: Source, node, flow, unit: Unit) -> dict:
    """Trace the actual expression alone, never its enclosing assertion.

    Control and uncertain mutation edges are excluded. Synthetic graph nodes
    may span a whole statement/function, so their spans are not evidence that
    every contained literal contributes a value to the observation.
    """
    if node is None:
        return {'spans': [], 'parameters': []}
    synthetic = {'assertion', 'join', 'parameter', 'receiver', 'unknown', 'may_effect'}
    roots = [n['id'] for n in flow.nodes
             if (n['start_byte'], n['end_byte']) == (node.start_byte, node.end_byte)
             and n['kind'] not in synthetic]
    todo, seen = list(roots), set()
    while todo:
        current = todo.pop()
        if current in seen:
            continue
        seen.add(current)
        todo.extend(n for n in flow.edges.get(current, ())
                    if flow.edge_kinds.get((current, n), 'value') == 'value'
                    and flow.nodes[n]['kind'] != 'assertion')
    values = {(node.start_byte, node.end_byte)}
    values.update((flow.nodes[n]['start_byte'], flow.nodes[n]['end_byte'])
                  for n in seen if flow.nodes[n]['kind'] not in synthetic)
    parameters = {flow.nodes[n]['parameter'] for n in seen if flow.nodes[n]['kind'] == 'parameter'}
    # This fallback is only for an absent expression node; it does not replace
    # the graph's temporal reaching definitions with a nearest-text heuristic.
    if not roots and node.type == 'identifier':
        name = source.text(node)
        if name in unit.params:
            parameters.add(name)
        definition = _value_definition(source, name, node.start_byte, unit.body)
        if definition is not None:
            inherited = _observation_value_trace(source, definition, flow, unit)
            values.update((s['start_byte'], s['end_byte']) for s in inherited['spans'])
            parameters.update(inherited['parameters'])
    return {'spans': [{'path': source.path, 'start_byte': a, 'end_byte': b} for a, b in sorted(values)],
            'parameters': sorted(parameters)}


def _helper_mappings(index: Index, unit: Unit, statement) -> list[dict]:
    """Keep exact actual/formal provenance, without guessing converted expectations."""
    if statement is None or statement.type not in CALLS:
        return []
    fn, args = call_parts(statement)
    result = []
    for uid, reason in index.resolve(unit, unit.source.text(fn)):
        if uid not in index.oracle_helpers or reason not in {'local_symbol', 'package_symbol', 'import_symbol'}:
            continue
        helper, hflow = index.units[uid], index.flow(uid)
        bindings = [{'parameter': p, 'slot': i, 'actual': expression(unit.source, a)}
                    for i, (p, a) in enumerate(zip(helper.params, args))]
        for assertion in hflow.assertions:
            _, actual, expected, predicate = _assertion_nodes(helper.source, assertion, helper)
            expected_text = helper.source.text(expected)
            direct = next((b for b in bindings if b['parameter'] == expected_text), None)
            # Include transitive parameter origins even when conversion prevents direct transfer.
            referenced = _identifier_reads(helper.source, expected)
            todo = list(referenced)
            seen = set()
            while todo:
                name = todo.pop()
                if name in seen:
                    continue
                seen.add(name)
                value = _value_definition(helper.source, name, expected.start_byte if expected else helper.node.end_byte, helper.body)
                if value is not None:
                    todo.extend(_identifier_reads(helper.source, value) - seen)
            origins = [b for b in bindings if b['parameter'] in seen]
            observed_trace = _observation_value_trace(helper.source, actual, hflow, helper)
            result.append({'helper_id': uid, 'assertion_span': {
                'path': helper.source.path, 'line': assertion.line, 'end_line': assertion.end_line},
                'predicate': predicate, 'observed': expression(helper.source, actual),
                'expected': expression(helper.source, expected), 'argument_bindings': bindings,
                'expected_parameter_origins': origins,
                'observed_parameter_origins': [b for b in bindings if b['parameter'] in observed_trace['parameters']],
                'observed_dependency_precision': 'actual_only_value_edges; mutation_and_control_unknown',
                'caller_expected': direct['actual'] if direct else None,
                'status': 'direct_parameter' if direct else 'unsupported_expected_transform_or_constant'})
    return result


def _unit_parameters(unit: Unit) -> list[dict]:
    """Retain row coupling, rather than independently recombining column values."""
    result = []
    table_nodes = []
    parent = unit.node.parent
    if parent is not None and parent.type == 'decorated_definition':
        for decorator in parent.named_children:
            if decorator.type != 'decorator':
                continue
            for call in walk(decorator):
                if call.type in CALLS:
                    fn, args = call_parts(call)
                    if unit.source.text(fn).endswith('.parametrize') and len(args) >= 2:
                        table_nodes.append(args[1])
    for table_index, table in enumerate(unit.parameter_rows):
        names = table['names']
        for row_index, row in enumerate(table['rows']):
            values = [row] if len(names) == 1 else row
            table_node = table_nodes[table_index] if table_index < len(table_nodes) else None
            row_nodes = [n for n in table_node.named_children if n.type != 'comment'] if table_node is not None else []
            row_node = row_nodes[row_index] if row_index < len(row_nodes) else None
            cells = ([row_node] if len(names) == 1 else [n for n in row_node.named_children if n.type != 'comment']) if row_node is not None else []
            result.append({'table': table_index, 'row': row_index,
                           'bindings': {name: json_safe(value) for name, value in zip(names, values)},
                           'binding_sources': {name: expression(unit.source, cell) for name, cell in zip(names, cells)},
                           'row_span': span(unit.source, row_node),
                           'source_span': span(unit.source, unit.node.parent if unit.node.parent is not None
                                               and unit.node.parent.type == 'decorated_definition' else unit.node),
                           'coupled': True})
    return result


def _fair_files(repository: Path, language: str, priority: Iterable[str], max_files: int | None):
    suffixes = {'python': {'.py'}, 'go': {'.go'}, 'typescript': {'.ts', '.tsx'}}[language]
    found = []
    for path in repository.rglob('*'):
        relative = path.relative_to(repository)
        if (path.is_file() and not path.is_symlink() and path.suffix in suffixes
                and not any(part in SKIP for part in relative.parts)
                and (is_test_path(relative.as_posix()) or path.name == 'conftest.py')
                and not (language == 'typescript' and '.test-d.' in path.name)):
            found.append(relative.as_posix())
    found = sorted(found)
    selected = [p for p in dict.fromkeys(priority) if (repository / p).is_file()
                and not Path(p).is_absolute() and '..' not in Path(p).parts]
    queues = collections.defaultdict(collections.deque)
    for name in found:
        if name not in selected:
            queues[str(Path(name).parent)].append(name)
    while queues and (max_files is None or len(selected) < max_files):
        for directory in sorted(queues):
            selected.append(queues[directory].popleft())
            if not queues[directory]:
                del queues[directory]
            if max_files is not None and len(selected) >= max_files:
                break
    return selected[:max_files] if max_files is not None else selected, len(found)


def _round_robin(groups, budget: int):
    """One item per test per round; registration order only breaks ties."""
    queues = collections.deque((key, iter(items)) for key, items in groups)
    selected = collections.defaultdict(list)
    count = 0
    while queues and count < budget:
        key, items = queues.popleft()
        try:
            selected[key].append(next(items))
        except StopIteration:
            continue
        count += 1
        queues.append((key, items))
    return selected


def _donor_candidates(unit: Unit):
    seen = set()
    # Start inside the test body: TS registration names and callbacks are
    # framework scaffolding, not program inputs or transferable expressions.
    for node in walk(unit.body):
        candidates = []
        if node.type in CALLS:
            candidates = [node, *call_parts(node)[1]]
        elif node.type in ASSIGNMENTS:
            value = child(node, 'right', 'value')
            if value is not None:
                candidates = list(value.named_children) if value.type == 'expression_list' else [value]
        elif node.type in LITERALS | CONTAINERS:
            candidates = [node]
        for candidate in candidates:
            key = (candidate.start_byte, candidate.end_byte)
            if key not in seen:
                seen.add(key)
                yield 'node', candidate
    for row in _unit_parameters(unit):
        yield 'parameter_row', row


def build_corpus(repository: Path | str, language: str, retrieval: dict | Path | str | None = None,
                 *, max_files: int | None = 400, max_capsules: int = 12000,
                 max_donors: int = 30000, top_k: int = 10) -> dict:
    """Build deterministic JSON data; never execute target or test code.

    Full sources/tests are shared rather than copied into each capsule. Every
    capsule's prefix_span denotes the complete source prefix inside its test;
    this remains available when the may-dependence slice misses hidden effects.
    """
    repository = Path(repository)
    if retrieval is None:
        retrieval = {}
    if isinstance(retrieval, (Path, str)):
        retrieval = json.loads(Path(retrieval).read_text())
    selected = [r for r in retrieval.get('selected_tests', []) if r.get('rank', 99999) <= top_k]
    priorities = [r['path'] for r in selected]
    paths, total_files = _fair_files(repository, language, priorities, max_files)
    sources, errors = [], []
    for name in paths:
        try:
            sources.append(Source(name, (repository / name).read_text(), language))
        except (OSError, UnicodeError) as exc:
            errors.append({'path': name, 'error': type(exc).__name__})
    # Historical selected tests without a repository file remain separate, possibly
    # incomplete compilation units. Multiple excerpts from one path must not hide
    # one another. Their original spans are provenance, not editable source spans.
    excerpt_origins = {}
    for row in selected:
        if row['path'] not in paths and row.get('code'):
            source_path = row['path'] + '#excerpt-' + str(row['line'])
            suffix = Path(row['path']).suffix
            source_language = {'.py': 'python', '.go': 'go', '.ts': 'typescript', '.tsx': 'typescript'}.get(suffix, language)
            source = Source(source_path, row['code'], source_language, origin='trajectory')
            excerpt_origins[source_path] = {'path': row['path'], 'line': row['line'],
                                            'name': row['name'], 'rank': row['rank']}
            sources.append(source)
    index = Index(sources, '')
    corpus = {'version': 1, 'language': language, 'capsules': [], 'donors': [], 'tests': {},
              'sources': {s.path: {'code': s.code, 'language': s.language, 'origin': s.origin,
                                    'sha256': hashlib.sha256(s.data).hexdigest(), 'parse_error': s.root.has_error,
                                    'complete_file': s.path not in excerpt_origins,
                                    'retrieval_excerpt': excerpt_origins.get(s.path)}
                          for s in sources}, 'coverage': {}}
    ranks = {(r['path'], r['name'], r['line']): r['rank'] for r in selected}
    ranks.update({(path, row['name'], 1): row['rank'] for path, row in excerpt_origins.items()})
    anchors = collections.defaultdict(list)
    for row in retrieval.get('anchors', []):
        anchors[(row.get('path'), row.get('name'), row.get('line'))].append(row)
    test_units = [u for u in index.units.values() if u.test and not u.source.type_only]
    test_units.sort(key=lambda u: (ranks.get((u.source.path, u.name, u.line), 99999), u.source.path, u.line))
    valid_flows = {}
    for unit in test_units:
        try:
            valid_flows[unit.id] = index.flow(unit.id)
        except (RecursionError, ValueError, KeyError) as exc:
            errors.append({'path': unit.source.path, 'test_id': unit.id, 'error': type(exc).__name__})
    capsule_plan = _round_robin(((u.id, list(enumerate(valid_flows[u.id].assertions)))
                                for u in test_units if u.id in valid_flows), max_capsules)
    donor_plan = _round_robin(((u.id, _donor_candidates(u)) for u in test_units if u.id in valid_flows), max_donors)
    donor_keys = set()
    no_oracle = 0
    for unit in test_units:
        source = unit.source
        flow = valid_flows.get(unit.id)
        if flow is None:
            continue
        rank = ranks.get((source.path, unit.name, unit.line))
        params = _unit_parameters(unit)
        support = _support(index, unit, flow)
        test_node = unit.node.parent if unit.node.parent is not None and unit.node.parent.type == 'decorated_definition' else unit.node
        containing_statement = test_node.parent if test_node.parent is not None and test_node.parent.type == 'expression_statement' else test_node
        enclosing_scope = containing_statement.parent
        while enclosing_scope is not None and enclosing_scope.type not in {'module', 'program', 'source_file', 'block', 'statement_block', 'class_definition'}:
            enclosing_scope = enclosing_scope.parent
        unit_calls = {(n.start_byte, n.end_byte): n for n in walk(unit.body) if n.type in CALLS}
        input_slots, call_records = _input_provenance(index, unit, flow, unit_calls)
        corpus['tests'][unit.id] = {'id': unit.id, 'name': unit.name, 'span': span(source, test_node),
                                  'definition_span': span(source, unit.node),
                                  'enclosing_scope_span': span(source, enclosing_scope),
                                  'insertion_after_byte': containing_statement.end_byte,
                                  'body_span': span(source, unit.body), 'retrieval_rank': rank,
                                  'parameters': unit.params, 'parameter_rows': params,
                                  'support': support, 'scope_bindings': sorted(_local_binders(source, unit.body) | set(unit.params))}
        parameterized = any('parametrize' in d for d in unit.decorators)
        if source.language == 'typescript' and unit.node.type in CALLS:
            parameterized |= '.each' in source.text(call_parts(unit.node)[0])
        corpus['tests'][unit.id]['parameterization_status'] = (
            'expanded_literal_rows' if params else 'unsupported_detected' if parameterized else 'none_detected')
        assertion_parts = {a.node: _assertion_nodes(source, a, unit) for a in flow.assertions}
        expected_nodes = [assertion_parts[a.node][2] for a in flow.assertions]
        oracle_spans = [s for node in expected_nodes for s in _oracle_value_spans(source, node, flow, unit)]
        helpers = {a.node: _helper_mappings(index, unit, assertion_parts[a.node][0])
                   for a in flow.assertions if a.predicate == 'assertion_helper'}
        source_nodes = {(n.start_byte, n.end_byte): n for n in walk(unit.body)}
        observation_traces = {}
        for assertion in flow.assertions:
            if assertion.predicate == 'assertion_helper':
                actuals = []
                for mapping in helpers.get(assertion.node, []):
                    for binding in mapping['observed_parameter_origins']:
                        actual_span = binding['actual']['span']
                        actual = source_nodes.get((actual_span['start_byte'], actual_span['end_byte']))
                        if actual is not None:
                            actuals.append(actual)
            else:
                actuals = [assertion_parts[assertion.node][1]]
            observation_traces[assertion.node] = [s for actual in actuals
                for s in _observation_value_trace(source, actual, flow, unit)['spans']]
        observation_spans = [s for spans in observation_traces.values() for s in spans]
        if not flow.assertions:
            no_oracle += 1
        for _, assertion in capsule_plan.get(unit.id, []):
            statement, observed, expected, predicate = assertion_parts[assertion.node]
            sliced = flow.slice([assertion.node])
            call_nodes = [unit_calls[(flow.nodes[c.node]['start_byte'], flow.nodes[c.node]['end_byte'])]
                          for c in flow.calls if c.node in sliced
                          and (flow.nodes[c.node]['start_byte'], flow.nodes[c.node]['end_byte']) in unit_calls]
            statement_span = span(source, statement)
            if statement_span is None:
                statement_span = {key: flow.nodes[assertion.node][key] for key in ('start_byte', 'end_byte', 'line', 'end_line')}
                statement_span['path'] = source.path
            prefix = {'path': source.path, 'start_byte': unit.body.start_byte,
                      'end_byte': statement_span['start_byte']}
            helper = helpers.get(assertion.node, [])
            for mapping in helper:
                mapped_expectations = [b['actual'] for b in mapping['expected_parameter_origins']]
                for mapped in mapped_expectations:
                    mapped_nodes = [n for n in walk(unit.body)
                                    if n.start_byte == mapped['span']['start_byte']
                                    and n.end_byte == mapped['span']['end_byte']]
                    expected_nodes.extend(mapped_nodes)
                    oracle_spans.extend(s for n in mapped_nodes for s in _oracle_value_spans(source, n, flow, unit))
            producer_calls = [call_records[(n.start_byte, n.end_byte)] for n in dict.fromkeys(call_nodes)
                              if (n.start_byte, n.end_byte) in call_records]
            atoms = expected_atoms(source, expected, before=statement_span['start_byte'], within=unit.body)
            producer_provenance = [{'callee': c['callee'], 'callee_identity': c['callee_identity'],
                                    'call_span': c['span'],
                                    'arguments': [{'slot': a['slot'], 'span': a['span'], 'text': a['text'],
                                                   'free_identifiers': a['free_identifiers']}
                                                  for a in c['arguments']]}
                                   for c in producer_calls]
            for atom in atoms:
                atom['observed_provenance'] = producer_provenance
                atom['provenance_precision'] = 'assertion_slice; field_specific_producer_unknown'
                oracle_spans.append(atom['expected']['span'])
            record = {'id': _id(source.path, unit.id, statement_span['start_byte'], assertion.predicate),
                      'test_id': unit.id, 'language': source.language, 'retrieval_rank': rank,
                      'assertion': assertion.text, 'assertion_span': statement_span,
                      'test_span': span(source, test_node), 'prefix_span': prefix,
                      'predicate': predicate, 'incidental': assertion.incidental,
                      'observation_side': ('right' if source.language == 'python'
                                           and assertion.expression_node.type == 'comparison_operator'
                                           and len(assertion.expression_node.named_children) == 2
                                           and observed == assertion.expression_node.named_children[1] else 'left_or_framework_actual'),
                      'observed': expression(source, observed), 'expected': expression(source, expected),
                      'expected_atoms': atoms,
                      'bindings': _binding_facts(flow, sliced), 'helper_assertions': helper,
                      'observation_value_sources': observation_traces[assertion.node],
                      'observation_dependency_precision': 'actual_only_value_edges; mutation_and_control_unknown',
                      'calls': producer_calls,
                      'parameter_rows': params,
                      'retrieval_anchor_ids': [a['id'] for a in anchors[(source.path, unit.name, assertion.line)]],
                      'unknowns': ['call_effects_and_aliases_not_proved', 'enclosing_fixture_and_scope_effects_not_proved']}
            if source.root.has_error:
                record['unknowns'].append('source_parse_error')
            if source.path in excerpt_origins:
                record['unknowns'].append('historical_excerpt_missing_full_file_support')
            if expected is None:
                record['unknowns'].append('no_direct_expected_expression')
            if parameterized and not params:
                record['unknowns'].append('parameter_rows_not_expanded')
            corpus['capsules'].append(record)
        # Expression donors include whole arguments and syntax literals/containers.
        # A literal program is never parsed as a special subject language.
        donor_nodes = [node for kind, node in donor_plan.get(unit.id, []) if kind == 'node']
        for node in donor_nodes:
            key = (source.path, node.start_byte, node.end_byte)
            if key in donor_keys or len(corpus['donors']) >= max_donors:
                continue
            donor_keys.add(key)
            record = expression(source, node)
            record.update({'id': _id(*key), 'test_id': unit.id, 'retrieval_rank': rank,
                           'call_context': _call_context(source, node, unit.node),
                           'input_slots': input_slots.get((node.start_byte, node.end_byte), []),
                           'role': 'expected' if any(_contains(n, node) for n in expected_nodes) else 'test_expression',
                           'binding_precision': 'syntactic_free_identifiers; aliases_and_shadowing_unknown'})
            record['oracle_dependency'] = (any(_contains(n, node) for n in expected_nodes)
                or any(s['start_byte'] <= node.start_byte and node.end_byte <= s['end_byte']
                       or node.start_byte <= s['start_byte'] and s['end_byte'] <= node.end_byte
                       for s in oracle_spans))
            record['observation_dependency'] = any(
                s['start_byte'] <= node.start_byte and node.end_byte <= s['end_byte']
                or node.start_byte <= s['start_byte'] and s['end_byte'] <= node.end_byte
                for s in observation_spans)
            record['dependency_role'] = (
                'observed_and_expected' if record['observation_dependency'] and record['oracle_dependency']
                else 'observed_only' if record['observation_dependency']
                else 'expected_only' if record['oracle_dependency'] else 'neither')
            if record['call_context'] is not None:
                context_span = record['call_context']['call_span']
                context_node = unit_calls.get((context_span['start_byte'], context_span['end_byte']))
                if context_node is not None:
                    record['call_context']['callee_identity'] = _callee_identity(index, unit, context_node)
                    record['context_parent'] = expression(source, context_node)
            if 'context_parent' not in record:
                record['context_parent'] = None
            record['context_relation_status'] = 'syntactic_containment_only; no_equivalence_claim'
            corpus['donors'].append(record)
        # Decorators live outside the function node: preserve the complete table
        # and coupled actual values, not just constants in the function body.
        for row in (row for kind, row in donor_plan.get(unit.id, []) if kind == 'parameter_row'):
            if len(corpus['donors']) >= max_donors:
                break
            corpus['donors'].append({'id': _id(unit.id, 'parameter_row', row['table'], row['row']),
                                     'kind': 'parameter_row', 'test_id': unit.id,
                                     'retrieval_rank': rank, 'parameter_bindings': row['bindings'],
                                     'binding_sources': row['binding_sources'], 'row_span': row['row_span'],
                                     'coupled': True, 'span': row['source_span'],
                                     'free_identifiers': [], 'call_context': None,
                                     'role': 'parameter_row', 'row': row['row'], 'table': row['table']})
    corpus['coverage'] = {'available_test_files': total_files, 'loaded_files': len(sources),
                          'file_budget': max_files, 'file_budget_exhausted': total_files > len(paths),
                          'test_units': len(test_units), 'tests_processed': len(corpus['tests']),
                          'tests_without_oracle': no_oracle,
                          'capsules': len(corpus['capsules']), 'donors': len(corpus['donors']),
                          'capsule_budget_exhausted': len(corpus['capsules']) >= max_capsules,
                          'donor_budget_exhausted': len(corpus['donors']) >= max_donors,
                          'sampling': 'retrieval_priority_then_one_item_per_test_per_round',
                          'errors': errors,
                          'limitations': ['may-dependence is not sound whole-language analysis',
                                          'parameter-row expansion currently supports literal pytest tables',
                                          'helper expectation conversions require explicit validation',
                                          'literal programs remain opaque',
                                          'capsules do not establish context equivalence']}
    return corpus


def source_text(corpus: dict, source_span: dict) -> str:
    """Recover exact bytes for an expression, test, or complete test prefix."""
    data = corpus['sources'][source_span['path']]['code'].encode()
    return data[source_span['start_byte']:source_span['end_byte']].decode()
