"""Compact, source-linked obligations for one fixed modified validation test.

This is a source representation, not an admission decision. Functions and call
sites occur once, including recursive calls. Production bodies never supply
oracles. ``render`` is the small, human-readable view intended for a bounded
semantic judgment; the structured form retains byte-accurate source links.
"""
from __future__ import annotations

import hashlib
import json

from anchor_retrieval.index import Index
from anchor_retrieval.graph import _locally_rebound
from anchor_retrieval.syntax import CALLS, call_parts, child, is_test_path, walk
from generic_composition.corpus import _assertion_nodes
from relation_search.admission import program_candidate
from relation_search.oracle_evidence import _modified_sources
from relation_search.recursive_validator_closure import _Graph, _span
from relation_search.test_roles import _Context, _guard_contexts, _owned
from relational_gap.frontend import _exception_observations


VERSION = 'compact-test-obligations.v3'
SEMANTICS = '''Judge only this fixed modified test with its supplied inputs,
fixtures and operation order. A source site is required only when normal
execution reaches it, with the lexical branches, prior returns/raises and
exception handling in the complete source respected. An expected-exception
region must exit through its matching exception adapter; a matching exception
may come from any reached operation in that region, including a helper or
assertion. Checks after that region require successful adapter exit. Do not
assume every lexical assertion executes or must pass independently of exception
consumption. Call arguments are evaluated at the source call site and bound to
the helper formals. Recursive edges describe the least reachable states from
these fixed inputs, not all possible helper inputs or a finite unrolling.
Production calls are opaque effects; their bodies are not expectation evidence.
Source coverage proves neither reachability, termination nor expectation truth.
Unresolved dispatch, callbacks, fixtures and unsupported controls stay unknown.'''


def _reference(position):
    return {'$span': {key: position[key] for key in ('path', 'start_byte', 'end_byte')}}


def _node_ref(source, node):
    return _reference(_span(source, node)) if node is not None else None


def _contains(outer, inner):
    return (outer['path'] == inner['path'] and outer['start_byte'] <= inner['start_byte']
            and inner['end_byte'] <= outer['end_byte'])


def _source_refs(value):
    """Replace copied source fields and spans; retain no generated code text."""
    if isinstance(value, list):
        return [_source_refs(item) for item in value]
    if not isinstance(value, dict):
        return value
    if {'path', 'start_byte', 'end_byte'} <= value.keys():
        return _reference(value)
    if 'span' in value and 'code' in value:
        return _reference(value['span'])
    return {key: _source_refs(item) for key, item in value.items()
            if key not in {'condition_text', 'header', 'callee_expression', 'external_state',
                           'parameters', 'values', 'decorators'}}


class _SourcePool:
    """Store each source byte once, even for nested callback definitions."""
    def __init__(self, sources):
        self.sources = {source.path: source for source in sources}

    def pack(self, document):
        ranges = {}

        def collect(value):
            if isinstance(value, list):
                for item in value:
                    collect(item)
            elif isinstance(value, dict):
                if '$span' in value:
                    position = value['$span']
                    source = self.sources[position['path']]
                    if not 0 <= position['start_byte'] <= position['end_byte'] <= len(source.data):
                        raise ValueError('source reference outside modified source')
                    ranges.setdefault(position['path'], set()).add((position['start_byte'], position['end_byte']))
                else:
                    for item in value.values():
                        collect(item)
        collect(document)
        blocks = {}
        for path in sorted(ranges):
            merged = []
            for start, end in sorted(ranges[path]):
                if merged and start <= merged[-1][1]:
                    merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
                else:
                    merged.append((start, end))
            for start, end in merged:
                identifier = 'S' + str(len(blocks))
                source = self.sources[path]
                blocks[identifier] = dict(path=path, start_byte=start, end_byte=end,
                                          code=source.data[start:end].decode())

        def replace(value):
            if isinstance(value, list):
                return [replace(item) for item in value]
            if not isinstance(value, dict):
                return value
            if '$span' in value:
                position = value['$span']
                for identifier, block in blocks.items():
                    if _contains(block, position):
                        return dict(source=identifier, start=position['start_byte'] - block['start_byte'],
                                    end=position['end_byte'] - block['start_byte'])
                raise ValueError('source reference has no source block')
            return {key: replace(item) for key, item in value.items()}
        return dict(sources=blocks, **replace(document))


def source_text(document, reference):
    """Resolve an exact UTF-8 byte reference emitted by :func:`analyze`."""
    block = document['sources'][reference['source']]
    return block['code'].encode()[reference['start']:reference['end']].decode()


def source_excerpt(document, reference, max_chars=320):
    """Return an exact character prefix with its full UTF-8 byte reference.

    ``omitted_chars`` counts Unicode characters, not bytes. The document always
    retains the full source; the prefix is only a bounded display convenience.
    """
    if not isinstance(max_chars, int) or isinstance(max_chars, bool) or max_chars < 0:
        raise ValueError('max_chars must be a nonnegative integer')
    text = source_text(document, reference)
    return dict(ref=dict(reference), text=text[:max_chars], omitted_chars=max(0, len(text) - max_chars))


def _guard_header(row, source, nodes):
    position = row['span']
    node = nodes.get((position['start_byte'], position['end_byte']))
    while node is not None and node.type != row['kind']:
        if node.start_byte != position['start_byte'] or node.end_byte != position['end_byte']:
            node = None
            break
        node = node.parent
    body = child(node, 'body', 'consequence') if node is not None else None
    # Existing lexical headers are exact byte prefixes. Validate them against
    # both the source and an AST body boundary before retaining the reference.
    existing = row.get('header')
    if existing:
        end = position['start_byte'] + len(existing.encode())
        if (end <= position['end_byte'] and (body is None or end <= body.start_byte)
                and source.data[position['start_byte']:end].decode() == existing):
            return dict(position, end_byte=end)
    if body is not None:
        return dict(position, end_byte=body.start_byte)
    if node is None:
        return None
    # Go switches/cases have direct delimiter tokens rather than a body field.
    # Looking only at direct children avoids braces in struct/interface types,
    # composite literals or function literals that belong to the header itself.
    delimiter = ':' if row['kind'] in {
        'type_case', 'expression_case', 'default_case', 'communication_case', 'case_statement'
    } else '{'
    token = next((part for part in node.children if part.type == delimiter), None)
    if token is None:
        return None
    return dict(position, end_byte=token.end_byte if delimiter == ':' else token.start_byte)


def _guards(rows, sources, nodes):
    result = []
    for row in rows:
        record = dict(kind=row['kind'], at=_reference(row['span']), branch=row.get('branch'),
                      condition=_reference(row['condition_span']) if row.get('condition_span') else None)
        position = row['span']
        header = _guard_header(row, sources[position['path']], nodes[position['path']])
        if header is not None:
            record['header'] = _reference(header)
        result.append(record)
    return result


class _CompactGraph(_Graph):
    def callable_value(self, context, node):
        # Fixture values and other formal parameters are not the same-named
        # module functions. Runtime function-valued parameters stay unresolved.
        if node.type == 'identifier' and context.unit.source.text(node) in context.unit.params:
            return None
        return super().callable_value(context, node)

    def fixtures(self, unit, vertex, ancestry=()):
        super().fixtures(unit, vertex, ancestry)
        if ancestry or unit.source.language != 'python':
            return
        # Named fixture parameters are modeled by the finite graph. Other
        # framework entry mechanisms must not disappear behind that coverage.
        for fixture in list(self.index.units.values()):
            if fixture.source.path != unit.source.path and not fixture.source.path.endswith('/conftest.py'):
                continue
            definition = fixture.node.parent
            if definition is None or definition.type != 'decorated_definition':
                continue
            for decorator in definition.named_children:
                if decorator.type != 'decorator' or not decorator.named_children:
                    continue
                expression = decorator.named_children[0]
                if expression.type not in CALLS:
                    continue
                fn, arguments = call_parts(expression)
                if any(argument.type == 'keyword_argument'
                       and fixture.source.text(child(argument, 'name')) == 'autouse'
                       and fixture.source.text(child(argument, 'value')) != 'False' for argument in arguments):
                    self.unknown('implicit_fixture_lifecycle_unproved',
                                 source=dict(span=_span(fixture.source, definition), code=fixture.source.text(definition)))
        definition = unit.node.parent
        if definition is not None and definition.type == 'decorated_definition':
            for decorator in definition.named_children:
                if decorator.type != 'decorator' or not decorator.named_children:
                    continue
                expression = decorator.named_children[0]
                fn = call_parts(expression)[0] if expression.type in CALLS else expression
                parts = unit.source.text(fn).split('.')
                imported = unit.source.imports.get(parts[0])
                parameter_adapter = ((imported == ('pytest', None) and parts[1:] == ['mark', 'parametrize'])
                                     or imported == ('pytest', 'mark') and parts[1:] == ['parametrize'])
                if not parameter_adapter:
                    self.unknown('root_decorator_dispatch_unproved',
                                 source=dict(span=_span(unit.source, decorator), code=unit.source.text(decorator)))

    def sites_for(self, vertex, unit):
        super().sites_for(vertex, unit)
        # The role walker intentionally rejects unproved assertion identities.
        # Keep their exact lexical matcher as a conditional source obligation,
        # with the identity uncertainty explicit. This local Flow inventory
        # never follows production bodies or requires callback input bindings.
        known = {tuple(site['source']['span'][key] for key in ('path', 'start_byte', 'end_byte'))
                 for site in self.sites if site['vertex'] == vertex}
        context = _Context(unit)

        def fallback(statement, proved, adapter):
            if statement is None:
                return
            position = _span(unit.source, statement)
            key = tuple(position[field] for field in ('path', 'start_byte', 'end_byte'))
            if key in known:
                return
            known.add(key)
            self.add_site(vertex, unit, statement, 'primitive_assertion_call', unit.source.text(statement),
                          _guard_contexts(unit.source, statement, unit.body),
                          adapter=adapter, adapter_identity='proved' if proved else 'unproved')
            if not proved:
                self.unknown('assertion_adapter_identity_unproved', vertex=vertex,
                             source=dict(span=position, code=unit.source.text(statement)))

        for assertion in self.index.flow(unit.id).assertions:
            if assertion.predicate == 'assertion_helper':
                continue
            statement, _, _, _ = _assertion_nodes(unit.source, assertion, unit)
            fallback(statement, self.analysis.assertion_supported(context, statement, assertion),
                     assertion.assertion_adapter)
        # Native Flow recognizes the conventional global spelling ``expect``.
        # Import aliases use the same source matcher shape for every method,
        # including toThrow/not.toThrow, without evaluating the callback.
        if unit.source.language == 'typescript':
            for statement in _owned(unit.body):
                if statement.type not in CALLS:
                    continue
                fn, _ = call_parts(statement)
                if fn is None:
                    continue
                for inner in walk(fn):
                    if inner.type not in CALLS:
                        continue
                    receiver, arguments = call_parts(inner)
                    if receiver is None or receiver.type != 'identifier' or not arguments:
                        continue
                    name = unit.source.text(receiver)
                    imported = unit.source.imports.get(name)
                    if imported not in {('vitest', 'expect'), ('@jest/globals', 'expect')}:
                        continue
                    proved = (name not in unit.params and not _locally_rebound(unit, name)
                              and not self.analysis.module_binding_conflict(unit.source, name))
                    fallback(statement, proved, 'imported_expect_matcher')
                    break
        # A one-statement block can have exactly the statement's byte extent.
        # Prefer the actual assertion/if node over a same-span block wrapper.
        for site in self.sites:
            if site['vertex'] != vertex:
                continue
            position = site['source']['span']
            exact = [node for node in walk(unit.body)
                     if node.start_byte == position['start_byte'] and node.end_byte == position['end_byte']]
            if any(node.type == 'assert_statement' for node in exact):
                site['passing_predicate']['form'] = 'assert_expression'
            elif any(node.type == 'if_statement' for node in exact):
                site['passing_predicate']['form'] = 'negated_failure_guard'
        guards = [site['source']['span'] for site in self.sites
                  if site['vertex'] == vertex and site['passing_predicate']['form'] == 'negated_failure_guard']
        self.sites[:] = [site for site in self.sites if not (
            site['vertex'] == vertex and site['passing_predicate']['form'] == 'uncaught_test_failure'
            and any(_contains(guard, site['source']['span']) for guard in guards))]


def _module_context(sources, represented):
    """Keep imports and referenced module assignments without production bodies.

    These are source facts, not evaluated values. Conditional/module initialization
    effects are deliberately not executed or substituted into expectations.
    """
    result = []
    by_path = {}
    for vertex in represented:
        by_path.setdefault(vertex['source']['span']['path'], []).append(vertex['source']['span'])
    imports = {'import_statement', 'import_from_statement', 'import_declaration', 'package_clause'}
    assignments = {'assignment', 'annotated_assignment', 'augmented_assignment',
                   'lexical_declaration', 'variable_declaration', 'const_declaration', 'var_declaration'}
    for source in sources:
        if source.path not in by_path:
            continue
        required = set()
        for node in walk(source.root):
            if node.type in {'identifier', 'type_identifier'} and any(
                    _contains(position, _span(source, node)) for position in by_path[source.path]):
                required.add(source.text(node))
        pending = []
        for node in source.root.named_children:
            if node.type in imports:
                result.append(dict(kind='module_import', at=_node_ref(source, node)))
                continue
            current = node.named_children[0] if node.type == 'expression_statement' and node.named_children else node
            if current.type in assignments:
                left = child(current, 'left', 'name')
                names = {source.text(item) for item in walk(left or current)
                         if item.type in {'identifier', 'type_identifier'}}
                pending.append((node, names))
        while pending:
            selected = [(node, names) for node, names in pending if names & required]
            if not selected:
                break
            for node, names in selected:
                result.append(dict(kind='module_binding', at=_node_ref(source, node)))
                required.update(source.text(item) for item in walk(node) if item.type == 'identifier')
                pending.remove((node, names))
    return result


def _compact(graph, sources, source_units, root, changes, imported_bindings):
    source_map = {source.path: source for source in sources}
    nodes = {source.path: {(node.start_byte, node.end_byte): node for node in walk(source.root)}
             for source in sources}
    units = {}
    for vertex in graph['vertices']:
        parameters = []
        for parameter in vertex['parameters']:
            parameters.append(dict(name=parameter['name'], at=_reference(parameter['span']),
                                   default=_reference(parameter['default']['span']) if parameter.get('default') else None,
                                   variadic=parameter['variadic'], keyword_only=parameter['keyword_only'],
                                   positional_only=parameter['positional_only']))
        path = vertex['source']['span']['path']
        provenance = ('fixed_test' if vertex['id'] == graph['root_vertex'] else
                      'test_source' if path == root.source.path or is_test_path(path) else
                      'source_testing_failure')
        units[vertex['id']] = dict(at=_reference(vertex['source']['span']),
                                   parameters=parameters, provenance=provenance)
    obligations = {}
    regions = []
    for site in graph['check_sites']:
        position = site['source']['span']
        source = source_map[position['path']]
        node = nodes[position['path']][position['start_byte'], position['end_byte']]
        kind = site['passing_predicate']['form']
        identifier = 'Q' + str(len(obligations))
        record = dict(unit=site['vertex'], kind=kind, at=_reference(position),
                      guards=_guards(site['guards'], source_map, nodes))
        for field in ('adapter', 'adapter_identity'):
            if field in site:
                record[field] = site[field]
        if kind == 'assert_expression':
            record['predicate'] = _node_ref(source, node.named_children[0])
        elif kind == 'negated_failure_guard':
            record['predicate'] = _node_ref(source, child(node, 'condition'))
            record['requires'] = 'guard_false_on_normal_completion'
        elif kind == 'expected_exception':
            unit = min((unit for unit in source_units
                        if unit.source.path == source.path and unit.node.start_byte <= node.start_byte
                        and node.end_byte <= unit.node.end_byte),
                       key=lambda unit: unit.node.end_byte - unit.node.start_byte)
            observations = list(_exception_observations(unit, [node]))
            if observations:
                record['expected'] = _node_ref(source, observations[0][2])
            body = child(node, 'body')
            record['region'] = _node_ref(source, body)
            record['requires'] = 'matching_exception_adapter_exit'
            regions.append((identifier, site['vertex'], _span(source, body)))
        elif kind == 'uncaught_test_failure':
            record['kind'] = 'testing_failure'
            record['requires'] = 'failure_not_reached_unless_consumed'
        else:
            record['predicate'] = _reference(position)
        obligations[identifier] = record
    calls = {}
    for edge in graph['transitions']:
        calls[edge['id']] = dict(caller=edge['caller'], callee=edge['callee'],
            at=_reference(edge['source']['span']), guards=_guards(edge['guards'], source_map, nodes),
            binding=edge['binding_status'], arguments=[dict(formal=row['formal'],
                actual=_reference(row['value']['span']), origin=row['origin']) for row in edge['transforms']],
            variadic_tail=_source_refs(edge['variadic_tail']))
    for row in list(obligations.values()) + list(calls.values()):
        position = row['at']['$span']
        row['exception_regions'] = [identifier for identifier, vertex, region in regions
                                    if vertex == row.get('unit', row.get('caller')) and _contains(region, position)]
    components = [dict(members=row['members'], recursive=row['recursive'],
                       internal_calls=row['internal_edges']) for row in graph['sccs']]
    boundaries = _source_refs(graph['opaque_boundaries'])
    for boundary in boundaries:
        if boundary['kind'] == 'resolved_production_callee':
            boundary['kind'] = 'resolved_production_or_unproved_validation'
            boundary['validation_provenance'] = 'not_established'
    return dict(root=graph['root_vertex'], units=units, obligations=obligations, calls=calls,
        entries=_source_refs(graph['entries']), sccs=components,
        boundaries=boundaries, unknowns=_source_refs(graph['unknowns']),
        module_context=_module_context(sources, graph['vertices']), imported_bindings=imported_bindings,
        edits=[dict(role=row['role'], original=row['original_span'], modified=_reference(row['span']))
               for row in changes])


def analyze(corpus, frontend, candidate, *, max_units=256, max_edges=2048):
    """Build compact source facts. ``frontend`` is accepted for caller symmetry.

    No provider, test execution, evaluation labels or reference implementation
    participates. A complete representation still has unconfirmed semantics.
    """
    result = dict(version=VERSION, status='unknown', semantic_validity='unconfirmed',
                  alarm_eligible=False, semantics=SEMANTICS)
    try:
        if max_units < 1 or max_edges < 0:
            raise ValueError('source budgets require max_units >= 1 and max_edges >= 0')
        candidate = program_candidate(candidate)
        sources, owner, changes, imports, import_unknowns = _modified_sources(corpus, candidate)
        builder = _CompactGraph(sources, owner, changes, max_units=max_units, max_edges=max_edges)
        selected = corpus['tests'][candidate['base_test_id']]
        definition = selected.get('definition_span', selected['span'])
        if definition['path'] != owner.path:
            raise ValueError('selected definition belongs to another source')
        # Decorator edits precede the function node. Recover its complete
        # modified extent from the already validated original-byte edits.
        # Names cannot identify an occurrence: other scopes may reuse them.
        def moved_boundary(position):
            delta = 0
            for change in changes:
                original = change['original_span']
                start, end = original['start_byte'], original['end_byte']
                if start < position < end:
                    raise ValueError('candidate edit crosses selected definition boundary')
                if end <= position:
                    delta += len(change['after'].encode()) - (end - start)
            return position + delta
        start = moved_boundary(definition['start_byte'])
        end = moved_boundary(definition['end_byte'])
        roots = [unit for unit in builder.index.units.values() if unit.source.path == owner.path
                 and unit.test and unit.node.start_byte == start and unit.node.end_byte == end]
        if len(roots) != 1:
            raise ValueError('modified root test not recovered')
        for unknown in import_unknowns:
            builder.unknown('modified_import_binding_unproved', **unknown)
        graph = builder.run(roots[0])
        document = _compact(graph, sources, builder.index.units.values(), roots[0], changes, imports)
        result.update(_SourcePool(sources).pack(document))
        result.update(status='complete' if not graph['unknowns'] else 'partial',
                      coverage=dict(source_sites_complete=not graph['unknowns'],
                                    reachability_proved=False, expectation_truth_proved=False,
                                    termination_proved=False, production_bodies_included=False),
                      candidate_id=candidate['id'],
                      source_sha256={source.path: hashlib.sha256(source.data).hexdigest() for source in sources})
    except (KeyError, ValueError, TypeError, AttributeError, RecursionError, StopIteration) as error:
        result.update(status='unknown', coverage=dict(source_sites_complete=False),
                      unknowns=[dict(code='compact_source_unavailable', detail=str(error))])
    finally:
        for method in (Index.module_paths, Index.reach, Index.field_factors):
            method.cache_clear()
    return result


def render(document):
    """Render complete code once and terse source-linked semantic obligations."""
    lines = [document.get('semantics', SEMANTICS), '', 'Source representation: ' + document['status']]
    for identifier, block in document.get('sources', {}).items():
        lines.extend(['', f"{identifier} {block['path']} bytes {block['start_byte']}:{block['end_byte']}",
                      '```', block['code'], '```'])
    def ref(value):
        return f"{value['source']}[{value['start']}:{value['end']}]"
    def snippet(value, limit=240):
        excerpt = source_excerpt(document, value, max_chars=limit)
        text = json.dumps(excerpt['text'], ensure_ascii=False)
        if excerpt['omitted_chars']:
            text += f"… [excerpt; {excerpt['omitted_chars']} chars omitted; full source {ref(value)}]"
        return text
    def compact_refs(value):
        if isinstance(value, dict):
            if set(value) == {'source', 'start', 'end'}:
                return ref(value)
            return {key: compact_refs(item) for key, item in value.items()}
        if isinstance(value, list):
            return [compact_refs(item) for item in value]
        return value
    lines.extend(['', 'Fixed root: ' + str(document.get('root'))])
    for identifier, unit in document.get('units', {}).items():
        lines.append(f"{identifier}: {ref(unit['at'])}; provenance={unit['provenance']}")
    def controls(row):
        pieces = []
        for guard in row.get('guards', []):
            value = guard.get('condition') or guard.get('header') or guard['at']
            text = f"{guard['kind']} {snippet(value)} {ref(value)} branch={guard['branch']}"
            if value != guard['at']:
                text += '; control=' + ref(guard['at'])
            else:
                text += '; header unavailable'
            pieces.append(text)
        if row.get('exception_regions'):
            pieces.append('exception consumption=' + ','.join(row['exception_regions']))
        return '; ' + '; '.join(pieces) if pieces else ''
    for identifier, row in document.get('obligations', {}).items():
        detail = '; requires=' + row['requires'] if 'requires' in row else ''
        if row.get('predicate'):
            detail += '; predicate=' + snippet(row['predicate'])
        if row.get('expected'):
            detail += '; expected=' + snippet(row['expected'])
        if row.get('adapter_identity'):
            detail += '; adapter_identity=' + row['adapter_identity']
        lines.append(f"{identifier} {row['unit']}: {row['kind']} {ref(row['at'])}" + detail + controls(row))
    for identifier, row in document.get('calls', {}).items():
        bindings = ', '.join(f"{item['formal']} <- {snippet(item['actual'])} {ref(item['actual'])} ({item['origin']})" for item in row['arguments'])
        lines.append(f"{identifier}: {row['caller']} -> {row['callee']} at {ref(row['at'])}; {row['binding']}; {bindings}" + controls(row))
    for component in document.get('sccs', []):
        if component['recursive']:
            lines.append('Recursive SCC: ' + ','.join(component['members']) + '; calls=' + ','.join(component['internal_calls']))
    for field in ('entries', 'module_context', 'imported_bindings', 'boundaries', 'unknowns'):
        rows = document.get(field, [])
        if rows:
            lines.append(field + ':')
            if field != 'boundaries':
                lines.extend(json.dumps(compact_refs(row), sort_keys=True, separators=(',', ':')) for row in rows)
                continue
            # Consecutive boundaries share classification facts. Factor those
            # constants into a group header and retain every remaining field in
            # exact, ordered rows; nothing is inferred or discarded.
            previous = None
            for row in rows:
                common = {key: row[key] for key in ('kind', 'semantic_support', 'validation_provenance') if key in row}
                if common != previous:
                    lines.append('shared ' + json.dumps(common, sort_keys=True, separators=(',', ':')))
                    previous = common
                varying = {key: item for key, item in row.items() if key not in common}
                lines.append(json.dumps(compact_refs(varying), sort_keys=True, separators=(',', ':')))
    return '\n'.join(lines)
