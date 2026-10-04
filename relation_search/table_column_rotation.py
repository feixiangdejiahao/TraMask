"""Rotate one source Go table column while preserving the complete test.

Bindings establish where values are used. They do not prove that independently
recombining columns preserves a contract. Every proposal needs full-test review.
"""
from __future__ import annotations

from collections import defaultdict
import hashlib
import json
import posixpath

from anchor_retrieval.syntax import Source, call_parts, child, walk
from experimental import relation_search_go_ts as syntax

VERSION = 'source-go-table-column-rotation.v1'
MAX_CANDIDATES = 16
POLICY = dict(
    version=VERSION, language='go', max_candidates=MAX_CANDIDATES,
    construction='Rotate one anonymous struct table column by a nonzero cyclic shift. Preserve all rows and the complete original test. Each changed cell is an exact input edit.',
    ordering='retrieval_rank, source path, test start, table start, shift, column',
    domain='Original module-level Test functions; unique direct local []struct table and range row; positional equal-width rows; unshadowed builtin scalar types and closed literal cells.',
    roles='Require a direct field use at a stable source or import call argument outside known oracle-only regions. Diagnostic or expected-only columns do not qualify. Shared input/oracle columns may qualify.',
    oracle='Full test, all assertions, helpers and other input columns remain unchanged. A dynamic expected expression does not prove arbitrary column independence.',
    semantic_status='hypothesis_pending_complete_test_contract_review',
    limitations=[
        'Table and row aliases, rebinding, mutation, address-taking and nested capture abstain.',
        'Only direct row-field call arguments and simple scalar expression wrappers are supported.',
        'Discarded call results cannot establish an input role; bare diagnostic or effect-only calls abstain.',
        'Source call declarations must be unique, nonvariadic and return a value; source void assertion helpers are not input consumers.',
        'Symmetric failure-guard operands have unresolved actual/expected roles and cannot alone establish an input consumer.',
        'Import signatures are not a type or contract proof. Native controls and independent semantic audit remain necessary.',
        'Field coupling, valid input domains, external effects, helper behavior and all untouched expectations require full-test review.',
    ],
    novelty_boundary='Multirow pairing transformation with explicit column provenance. Existing literal edits can overlap individual cell changes.',
    forbidden_inputs=['case identifiers', 'historical candidates', 'runtime outcomes', 'audit labels', 'hidden tests', 'reference implementations'],
)

SCALARS = {'string', 'bool', 'int', 'int8', 'int16', 'int32', 'int64',
           'uint', 'uint8', 'uint16', 'uint32', 'uint64', 'uintptr', 'byte', 'rune',
           'float32', 'float64', 'complex64', 'complex128'}
NUMBERS = {'int_literal', 'float_literal', 'imaginary_literal', 'rune_literal'}
WRAPPERS = {'parenthesized_expression', 'binary_expression', 'unary_expression'}
WRITES = {'short_var_declaration', 'assignment_statement', 'var_spec', 'const_spec',
          'range_clause', 'inc_statement', 'dec_statement', 'parameter_declaration',
          'variadic_parameter_declaration', 'type_spec', 'type_alias'}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def _receipt(source, node):
    return dict(path=source.path, start_byte=node.start_byte, end_byte=node.end_byte,
                line=node.start_point.row + 1, end_line=node.end_point.row + 1,
                source_sha256=hashlib.sha256(source.data).hexdigest(), text=source.text(node))


def _span(source, node):
    return {key: value for key, value in _receipt(source, node).items()
            if key not in {'source_sha256', 'text'}}


def _inside(inner, outer):
    return outer.start_byte <= inner.start_byte and inner.end_byte <= outer.end_byte


def _parts(node):
    return [n for n in node.named_children if n.type != 'comment'] if node else []


def _unwrap(node):
    while node is not None and node.type in {'literal_element', 'expression_list'} and len(_parts(node)) == 1:
        node = _parts(node)[0]
    return node


def _statements(body):
    parts = _parts(body)
    return _parts(parts[0]) if len(parts) == 1 and parts[0].type == 'statement_list' else parts


def _package(source):
    clause = next(n for n in source.root.named_children if n.type == 'package_clause')
    return posixpath.dirname(source.path), source.text(clause).removeprefix('package').strip()


def _targets(node):
    if node.type in {'var_spec', 'const_spec', 'parameter_declaration', 'variadic_parameter_declaration', 'type_spec', 'type_alias'}:
        return node.children_by_field_name('name')
    if node.type in {'inc_statement', 'dec_statement'}:
        return _parts(node)
    left = child(node, 'left')
    return _parts(left) if left is not None and left.type == 'expression_list' else [left] if left else []


def _writes(source, scope):
    result = defaultdict(list)
    for node in walk(scope):
        if node.type in WRITES:
            for target in _targets(node):
                for name in walk(target):
                    if name.type in {'identifier', 'type_identifier'}:
                        result[source.text(name)].append(node)
    return result


class _Directory:
    def __init__(self, corpus, frontend):
        self.files, self.functions, self.names = {}, defaultdict(list), defaultdict(list)
        for path, row in sorted(corpus['sources'].items()):
            if row.get('origin') != 'repository' or row.get('language') != 'go':
                continue
            if frontend.get('sources', {}).get(path, {}).get('code') != row['code']:
                raise ValueError('frontend_source_mismatch:' + path)
            source = Source(path, row['code'], 'go', 'repository')
            if source.root.has_error or not any(n.type == 'package_clause' for n in source.root.named_children):
                continue
            self.files[path] = source
            package = _package(source)
            for node in source.root.named_children:
                if node.type == 'function_declaration':
                    key = package + (source.text(child(node, 'name')),)
                    self.functions[key].append((source, node))
                    self.names[key].append(node)
                elif node.type in {'type_declaration', 'var_declaration', 'const_declaration'}:
                    for spec in walk(node):
                        if spec.type in {'type_spec', 'type_alias', 'var_spec', 'const_spec'}:
                            for name in spec.children_by_field_name('name'):
                                self.names[package + (source.text(name),)].append(spec)


def _closed(source, node, typ):
    if typ == 'string':
        return node.type in {'interpreted_string_literal', 'raw_string_literal'}
    if typ == 'bool':
        return node.type in {'true', 'false'}
    if node.type == 'unary_expression':
        parts = _parts(node)
        return (len(parts) == 1 and source.text(node).lstrip().startswith(('+', '-'))
                and parts[0].type in NUMBERS and _closed(source, parts[0], typ))
    numeric = NUMBERS if typ.startswith('complex') else NUMBERS - {'imaginary_literal'}
    if not typ.startswith(('float', 'complex')):
        numeric -= {'float_literal'}
    return node.type in numeric


class _Test:
    def __init__(self, directory, source, node, record, observations):
        self.directory, self.source, self.node, self.record = directory, source, node, record
        self.body = child(node, 'body')
        self.writes = _writes(source, node)
        self.package = _package(source)
        self.parameters = []
        for param in _parts(child(node, 'parameters')):
            typ = source.text(child(param, 'type'))
            self.parameters.extend((source.text(name), typ, param) for name in param.children_by_field_name('name'))
        if len(self.parameters) != 1:
            raise ValueError('test_parameter_binding_unresolved')
        testing_name, typ, parameter = self.parameters[0]
        expected_types = {'*' + alias + '.T' for alias, target in source.imports.items() if target == ('testing', None)}
        if typ not in expected_types or self.writes[testing_name] != [parameter]:
            raise ValueError('testing_parameter_rebound_or_unresolved')
        if '.' in source.imports:
            raise ValueError('dot_import_binding_unknown')
        self.testing_name = testing_name
        # Treat both operands of an unmodelled failure guard as role-unknown.
        # Later ordinary API uses keep shared definitions outside these regions.
        extra = []
        for call in walk(self.body):
            if call.type == 'call_expression' and self._testing_call(call):
                extra.extend(dict(kind='assertion', expected=dict(span=_span(source, argument)))
                             for argument in call_parts(call)[1])
        for conditional in walk(self.body):
            if conditional.type != 'if_statement':
                continue
            condition = child(conditional, 'condition')
            consequence = child(conditional, 'consequence')
            if condition is not None and consequence is not None and any(
                    self._testing_call(n, {'Error', 'Errorf', 'Fatal', 'Fatalf', 'Fail', 'FailNow'})
                    for n in walk(consequence) if n.type == 'call_expression'):
                extra.append(dict(kind='assertion', expected=dict(span=_span(source, condition))))
        self.oracle_regions = syntax._expected_regions(source, [*observations, *extra])

    def _testing_call(self, call, names=None):
        function, _ = call_parts(call)
        path = syntax._path(self.source, function)
        return (path is not None and len(path) == 2 and path[0] == self.testing_name
                and (names is None or path[1] in names))

    def covered(self, node):
        return any(start <= node.start_byte and node.end_byte <= end for start, end in self.oracle_regions)

    def consumer(self, call, argument):
        source = self.source
        function, arguments = call_parts(call)
        if (argument not in arguments or self.covered(call) or syntax._assertion_call(source, call)
                or self._testing_call(call) or call.parent.type == 'expression_statement'):
            return None
        path = syntax._path(source, function)
        if not path or path[0] in self.writes:
            raise ValueError('input_call_binding_unresolved_or_shadowed')
        if len(path) == 2 and path[0] in source.imports:
            module, member = source.imports[path[0]]
            if member is not None or path[0] in {'.', '_'}:
                raise ValueError('input_import_binding_unresolved')
            return dict(kind='stable_import_argument', binding=[module, path[1]],
                        call=_receipt(source, call), argument_index=arguments.index(argument))
        if len(path) != 1:
            raise ValueError('input_receiver_binding_unresolved')
        key = self.package + (path[0],)
        definitions = self.directory.functions[key]
        if len(definitions) != 1 or len(self.directory.names[key]) != 1:
            raise ValueError('input_source_function_not_unique')
        owner, declaration = definitions[0]
        parameters = []
        for param in _parts(child(declaration, 'parameters')):
            if param.type != 'parameter_declaration':
                raise ValueError('input_source_variadic_or_generic')
            parameters.extend(owner.text(name) for name in param.children_by_field_name('name'))
        if child(declaration, 'type_parameters') is not None or len(parameters) != len(arguments):
            raise ValueError('input_source_argument_binding_unresolved')
        if child(declaration, 'result') is None:
            return None
        formal = parameters[arguments.index(argument)]
        helper_body = child(declaration, 'body')
        helper_calls = [n for n in walk(helper_body) if n.type == 'call_expression']
        if any(syntax._assertion_call(owner, n) for n in helper_calls):
            # A returned status does not turn an assertion-only helper into a
            # subject consumer. Setup helpers may also consume the parameter
            # in an ordinary operation before checking its error result.
            regions = syntax._expected_regions(owner)
            uses = [n for n in helper_calls if not syntax._assertion_call(owner, n)
                    and not any(start <= n.start_byte and n.end_byte <= end for start, end in regions)
                    and any(part.type == 'identifier' and owner.text(part) == formal
                            for arg in call_parts(n)[1] for part in walk(arg))]
            declarations_of_formal = _writes(owner, declaration)[formal]
            if (not uses or len(declarations_of_formal) != 1
                    or declarations_of_formal[0].type != 'parameter_declaration'):
                return None
        return dict(kind='unique_source_returning_function_argument', binding=[*self.package, path[0]],
                    call=_receipt(source, call), declaration=_receipt(owner, declaration),
                    argument_index=arguments.index(argument), parameter=formal)

    def column_uses(self, loop, row_name, fields):
        source = self.source
        proofs, rejected = defaultdict(list), {}
        for node in walk(child(loop, 'body')):
            if node.type != 'identifier' or source.text(node) != row_name:
                continue
            selector = node.parent
            if selector.type != 'selector_expression' or child(selector, 'operand') != node:
                raise ValueError('row_alias_or_nonfield_use')
            field = source.text(child(selector, 'field'))
            if field not in fields:
                raise ValueError('row_field_unresolved')
            parent = selector.parent
            while parent is not None and parent != loop:
                if parent.type in {'func_literal', 'go_statement', 'defer_statement'}:
                    raise ValueError('row_capture_or_deferred_use')
                if parent.type == 'unary_expression' and source.text(parent).lstrip().startswith('&'):
                    raise ValueError('row_address_escape')
                if parent.type in WRITES and any(_inside(selector, target) for target in _targets(parent)):
                    raise ValueError('row_or_field_written')
                parent = parent.parent
            if self.covered(selector):
                continue
            current = selector
            while current.parent is not None and current.parent.type in WRAPPERS:
                current = current.parent
            parent = current.parent
            if parent is None or parent.type != 'argument_list' or parent.parent.type != 'call_expression':
                rejected[field] = 'field_use_not_direct_stable_call_argument'
                continue
            call = parent.parent
            try:
                proof = self.consumer(call, current)
            except ValueError as error:
                rejected[field] = str(error)
                continue
            if proof is not None:
                proofs[field].append(dict(proof, field_use=_receipt(source, selector)))
        return proofs, rejected

    def table(self, literal):
        source = self.source
        typ = child(literal, 'type')
        if typ is None or typ.type != 'slice_type' or child(typ, 'element').type != 'struct_type':
            raise ValueError('table_not_anonymous_struct_slice')
        struct = child(typ, 'element')
        fields = []
        for field in _parts(next(n for n in struct.named_children if n.type == 'field_declaration_list')):
            type_node = child(field, 'type')
            name_nodes = field.children_by_field_name('name')
            field_type = source.text(type_node)
            if (field.type != 'field_declaration' or not name_nodes or field_type not in SCALARS
                    or type_node.type != 'type_identifier' or child(field, 'tag') is not None
                    or field_type in self.writes or field_type in source.imports
                    or self.directory.names[self.package + (field_type,)]):
                raise ValueError('field_not_unshadowed_builtin_scalar')
            fields.extend((source.text(name), field_type) for name in name_nodes)
        if not fields or len({name for name, _ in fields}) != len(fields) or any(name == '_' for name, _ in fields):
            raise ValueError('field_names_not_unique')
        rows = []
        for element in _parts(child(literal, 'body')):
            row = _unwrap(element)
            cells = [_unwrap(n) for n in _parts(row)]
            if row.type != 'literal_value' or len(cells) != len(fields):
                raise ValueError('rows_not_positional_equal_width')
            if any(not _closed(source, cell, field_type) for cell, (_, field_type) in zip(cells, fields)):
                raise ValueError('cell_not_closed_scalar_of_declared_type')
            rows.append(cells)
        if len(rows) < 2:
            raise ValueError('table_has_fewer_than_two_rows')
        if any(field_type == 'bool' for _, field_type in fields) and any(
                name in self.writes or name in source.imports or self.directory.names[self.package + (name,)]
                for name in ('true', 'false')):
            raise ValueError('boolean_constant_shadowed')
        assignment = literal.parent
        if assignment.type == 'expression_list':
            if len(_parts(assignment)) != 1:
                raise ValueError('table_assignment_not_single')
            assignment = assignment.parent
        if assignment.type not in {'short_var_declaration', 'var_spec'}:
            raise ValueError('table_not_unique_local_variable')
        targets = _targets(assignment)
        if len(targets) != 1 or targets[0].type != 'identifier':
            raise ValueError('table_assignment_not_single')
        outer = assignment.parent if assignment.type == 'var_spec' else assignment
        if outer not in _statements(self.body) or (assignment.type == 'var_spec' and len(_parts(outer)) != 1):
            raise ValueError('table_not_direct_test_local')
        name = source.text(targets[0])
        if name == '_' or self.writes[name] != [assignment]:
            raise ValueError('table_rebound_or_shadowed')
        uses = [n for n in walk(self.node) if n.type == 'identifier' and source.text(n) == name and n != targets[0]]
        if len(uses) != 1 or uses[0].parent.type != 'range_clause' or child(uses[0].parent, 'right') != uses[0]:
            raise ValueError('table_alias_or_nonunique_range')
        clause, loop = uses[0].parent, uses[0].parent.parent
        if loop.type != 'for_statement' or loop not in _statements(self.body) or loop.start_byte < assignment.end_byte:
            raise ValueError('range_not_direct_after_table')
        left = _parts(child(clause, 'left'))
        if (len(left) != 2 or source.text(left[0]) != '_' or left[1].type != 'identifier'
                or ':=' not in source.text(clause)[:source.text(clause).find('range')]):
            raise ValueError('range_row_binding_not_unique')
        row_name = source.text(left[1])
        if row_name == '_' or self.writes[row_name] != [clause]:
            raise ValueError('row_rebound_or_shadowed')
        for occurrence in walk(self.node):
            if occurrence.type == 'identifier' and source.text(occurrence) == row_name and occurrence != left[1] and not _inside(occurrence, child(loop, 'body')):
                raise ValueError('row_binding_used_outside_range')
        proofs, rejected = self.column_uses(loop, row_name, {name for name, _ in fields})
        return fields, rows, proofs, rejected, dict(table=_receipt(source, literal),
            table_binding=_receipt(source, assignment), range_binding=_receipt(source, clause),
            original_test=_receipt(source, self.node), oracle_preservation_proved=False,
            semantic_status=POLICY['semantic_status'])


def generate(corpus, frontend, issue='', *, limit=MAX_CANDIDATES):
    del issue
    if type(limit) is not int or limit < 0:
        raise ValueError('limit_must_be_nonnegative_integer')
    limit = min(limit, MAX_CANDIDATES)
    if corpus['language'] != 'go':
        return dict(version=VERSION, status='language_unsupported', candidates=[], total_candidates=0, skipped=[])
    directory = _Directory(corpus, frontend)
    candidates, skipped = [], []
    for identifier, record in corpus['tests'].items():
        source = directory.files.get(record['span']['path'])
        if source is None or not source.path.endswith('_test.go'):
            continue
        nodes = [n for n in source.root.named_children if n.type == 'function_declaration'
                 and n.start_byte == record.get('definition_span', record['span'])['start_byte']]
        if len(nodes) != 1:
            continue
        node = nodes[0]
        if not source.text(child(node, 'name')).startswith('Test'):
            continue
        if len(directory.functions[_package(source) + (source.text(child(node, 'name')),)]) != 1:
            skipped.append(dict(base_test_id=identifier, reason='test_registration_not_unique'))
            continue
        if (record['span']['start_byte'], record['span']['end_byte']) != (node.start_byte, node.end_byte):
            skipped.append(dict(base_test_id=identifier, reason='incomplete_original_test_span'))
            continue
        literals = [n for n in walk(child(node, 'body')) if n.type == 'composite_literal'
                    and child(n, 'type') is not None and child(n, 'type').type == 'slice_type'
                    and child(child(n, 'type'), 'element') is not None
                    and child(child(n, 'type'), 'element').type == 'struct_type']
        if not literals:
            continue
        try:
            scope = _Test(directory, source, node, record, frontend.get('observations', []))
        except ValueError as error:
            skipped.append(dict(base_test_id=identifier, reason=str(error)))
            continue
        for literal in literals:
            try:
                fields, rows, proofs, rejected, evidence = scope.table(literal)
            except ValueError as error:
                skipped.append(dict(base_test_id=identifier, table_start=literal.start_byte, reason=str(error)))
                continue
            for index, (name, _) in enumerate(fields):
                if name in rejected or not proofs[name]:
                    skipped.append(dict(base_test_id=identifier, table_start=literal.start_byte, column=index,
                        field=name, reason=rejected.get(name, 'no_non_oracle_input_consumer')))
            for shift in range(1, len(rows)):
                for column, (name, field_type) in enumerate(fields):
                    if name in rejected or not proofs[name]:
                        continue
                    edits, mapping = [], []
                    for index, cells in enumerate(rows):
                        target, donor = cells[column], rows[(index + shift) % len(rows)][column]
                        mapping.append(dict(row=index, donor_row=(index + shift) % len(rows),
                                            target=_receipt(source, target), donor=_receipt(source, donor)))
                        if source.text(target) != source.text(donor):
                            edits.append(dict(span=_span(source, target), before=source.text(target),
                                              after=source.text(donor), role='input'))
                    if not edits:
                        continue
                    key = 'colrotate_' + digest([VERSION, identifier, edits])[:24]
                    rank = record.get('retrieval_rank')
                    rank = rank if type(rank) is int and rank >= 0 else 10**12
                    candidates.append(dict(id=key, base_test_id=identifier, source_test_ids=[identifier],
                        imports=[], edits=edits, generator=VERSION, operator='table_column_cyclic_rotation',
                        kind='source_table_pairing_hypothesis', oracle_status=POLICY['semantic_status'],
                        source_evidence=dict(evidence, column=column, field=name, field_type=field_type,
                            shift=shift, row_count=len(rows), rotation=mapping, input_consumers=proofs[name]),
                        order=[rank, source.path, node.start_byte, literal.start_byte, shift, column]))
    # Repeated values can make distinct shifts yield the same complete edit.
    unique = {}
    for candidate in sorted(candidates, key=lambda row: row['order']):
        unique.setdefault(candidate['id'], candidate)
    values = list(unique.values())
    return dict(version=VERSION, status='source_hypotheses', candidates=values[:limit],
                total_candidates=len(values), selected=min(limit, len(values)), skipped=skipped)
