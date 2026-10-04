"""Construct source-bound Go tests for a public quantitative contract.

The relation comes from a reviewed discovery record. Signatures and exact
quotations establish provenance, not truth of the proposed inequality. No
target function executes during catalog construction or test generation.
"""
from __future__ import annotations

from collections import defaultdict
import hashlib
import json
import posixpath
import re

from anchor_retrieval.syntax import Source, child, walk
from relation_search.oracle import issue_contract

VERSION = 'source-quantity-bound-go.v1'
IR_VERSION = 'public-quantity-bound-relation.v1'
LAW = 'output_measure_le_positive_input_bound'
BOUNDS = (1, 2, 4, 8)
MAX_STRINGS = 8
MAX_LITERAL_BYTES = 256
MAX_OPTIONS = 16
POLICY = dict(
    version=VERSION, language='go', relation=LAW,
    construction='Append an independent block to the first supported original same-package test. Measure F on at most eight source string literals and four positive bounds.',
    ordering='Source path and declaration position; relation declaration order; zero options then one public field at a time in declaration order.',
    inputs='Only directly readable printable ASCII string literals inside repository source tests, including empty strings. Filter this domain before taking the first eight literals. Raw contents must use characters 0x20 through 0x7e. Interpreted literals must also contain no backslash or escape. No trajectory source, runtime result, or implementation-derived expected value.',
    input_domain='Printable ASCII text only; no claim of ANSI control-sequence or Unicode coverage. String option length remains unrestricted relative to the bound.',
    bounds=list(BOUNDS), max_strings=MAX_STRINGS, max_option_configurations=MAX_OPTIONS,
    per_candidate_transform_call_upper_bound=MAX_STRINGS * len(BOUNDS),
    per_candidate_measure_call_upper_bound=MAX_STRINGS * len(BOUNDS),
    unchanged='The complete original test and all its expectations precede the appended block.',
    semantic_obligations=[
        'Public evidence must guarantee the inequality for every selected positive bound, source string and option configuration.',
        'The measurement unit must match the bound parameter. The unit label is not a proof.',
        'The chosen observer must measure the contract quantity and accept every produced value.',
        'Added calls must not invalidate original cleanup or shared-state obligations.',
        'A passing source control establishes execution context, not oracle correctness.',
    ],
    forbidden_inputs=['task identities', 'audit labels', 'historical candidates', 'hidden tests', 'reference implementations'],
    limitations=[
        'Public same-package Go functions only; one string and one int input, with an optional local named struct.',
        'Struct fields must all be public string or bool fields; embedded and unsupported fields abstain.',
        'Cross-package aliases require explicit frontend Go module mappings.',
        'Only a straight-line original test with a verified testing.T parameter is used.',
        'Strings containing controls, non-ASCII characters, or interpreted escapes abstain; no Go string decoder is used.',
        'Type checks and source receipts do not prove the discovered natural-language contract or purity.',
    ],
)
IR_SCHEMA = dict(version=IR_VERSION, relations=[dict(
    id='discovery identifier', law=LAW, unit='nonempty quantity unit',
    transform=dict(declaration='complete declaration receipt', string_parameter=0,
                   bound_parameter=1, options_parameter=None),
    measure=dict(declaration='complete declaration receipt'),
    evidence=['exact issue or public documentation receipts'],
    semantic_status='hypothesis_pending_independent_audit',
)])


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def receipt(path, code, start_byte, end_byte):
    data = code.encode()
    return dict(path=path, source_sha256=hashlib.sha256(data).hexdigest(),
                start_byte=start_byte, end_byte=end_byte, text=data[start_byte:end_byte].decode())


def _package(source):
    node = next(n for n in source.root.named_children if n.type == 'package_clause')
    return posixpath.dirname(source.path), source.text(node).removeprefix('package').strip()


def _types(source, node):
    if node is None:
        return []
    if node.type != 'parameter_list':
        return [source.text(node)]
    out = []
    for declaration in node.named_children:
        if declaration.type != 'parameter_declaration':
            raise ValueError('variadic_or_unsupported_parameters')
        typ = child(declaration, 'type')
        names = [n for n in declaration.named_children if n != typ]
        out.extend([source.text(typ)] * max(1, len(names)))
    return out


def _node_receipt(source, node):
    return receipt(source.path, source.code, node.start_byte, node.end_byte)


def _public_docs(source, node):
    preceding = []
    cursor = node.start_byte
    for sibling in reversed(source.root.named_children):
        if sibling.end_byte > cursor:
            continue
        if sibling.type != 'comment' or source.data[sibling.end_byte:cursor].strip():
            break
        preceding.append(sibling)
        cursor = sibling.start_byte
    if not preceding:
        return None
    return receipt(source.path, source.code, preceding[-1].start_byte, preceding[0].end_byte)


def _files(corpus, frontend=None):
    files = {}
    for path, row in sorted(corpus['sources'].items()):
        if row.get('origin') != 'repository' or row.get('language') != 'go':
            continue
        if frontend is not None and frontend.get('sources', {}).get(path, {}).get('code') != row['code']:
            raise ValueError('frontend_source_mismatch:' + path)
        source = Source(path, row['code'], 'go')
        if not source.root.has_error and any(n.type == 'package_clause' for n in source.root.named_children):
            files[path] = source
    return files


class _Directory:
    def __init__(self, corpus, frontend=None):
        self.files = _files(corpus, frontend)
        self.modules = (frontend or {}).get('module_resolution', {}).get('go_modules', {})
        self.types = defaultdict(list)
        self.functions = defaultdict(list)
        self.names = defaultdict(set)
        self.test_names = defaultdict(set)
        self.packages = defaultdict(set)
        for source in self.files.values():
            package = _package(source)
            if source.path.endswith('_test.go'):
                for node in source.root.named_children:
                    if node.type == 'function_declaration':
                        self.test_names[package].add(source.text(child(node, 'name')))
                    elif node.type in {'type_declaration', 'var_declaration', 'const_declaration'}:
                        for spec in node.named_children:
                            for name_node in spec.named_children:
                                if name_node == child(spec, 'type'):
                                    break
                                if name_node.type in {'identifier', 'type_identifier'}:
                                    self.test_names[package].add(source.text(name_node))
                continue
            self.packages[package[0]].add(package)
            for node in source.root.named_children:
                if node.type == 'function_declaration':
                    name = source.text(child(node, 'name'))
                    self.functions[package + (name,)].append((source, node))
                    self.names[package].add(name)
                elif node.type in {'type_declaration', 'var_declaration', 'const_declaration'}:
                    for spec in node.named_children:
                        for name_node in spec.named_children:
                            if name_node == child(spec, 'type'):
                                break
                            if name_node.type in {'identifier', 'type_identifier'}:
                                self.names[package].add(source.text(name_node))
                        if spec.type in {'type_spec', 'type_alias'}:
                            name = source.text(child(spec, 'name'))
                            self.types[package + (name,)].append((source, spec))

    def imported_package(self, source, alias):
        target = source.imports.get(alias)
        if not target or alias in {'.', '_'}:
            raise ValueError('type_import_unresolved')
        module = target[0]
        matches = []
        for directory, prefix in self.modules.items():
            if module == prefix or module.startswith(prefix + '/'):
                suffix = module[len(prefix):].lstrip('/')
                path = posixpath.normpath(posixpath.join(directory, suffix))
                path = '' if path == '.' else path
                if path.startswith('../') or path == '..' or path.startswith('/'):
                    continue
                matches.append((len(prefix), path))
        if not matches:
            raise ValueError('type_import_has_no_explicit_local_module_mapping')
        longest = max(length for length, _ in matches)
        paths = {path for length, path in matches if length == longest}
        if len(paths) != 1:
            raise ValueError('type_import_module_mapping_ambiguous')
        packages = self.packages[next(iter(paths))]
        if len(packages) != 1:
            raise ValueError('type_import_package_unresolved_or_ambiguous')
        return next(iter(packages))

    def resolve(self, source, text, seen=()):
        package = _package(source)
        if '.' in text:
            alias, name = text.split('.', 1)
            if not re.fullmatch(r'[A-Za-z_]\w*', name):
                raise ValueError('unsupported_qualified_type')
            package = self.imported_package(source, alias)
        else:
            name = text
        key = package + (name,)
        if key in seen or len(seen) >= 16:
            raise ValueError('recursive_or_deep_type_alias')
        definitions = self.types.get(key, [])
        if not definitions:
            if '.' not in text and name in {'string', 'int', 'bool'} and name not in self.names[package]:
                return dict(kind=name, declarations=[])
            raise ValueError('type_binding_unresolved')
        if len(definitions) != 1:
            raise ValueError('type_binding_ambiguous')
        owner, spec = definitions[0]
        if child(spec, 'type_parameters') is not None:
            raise ValueError('generic_type_unsupported')
        typ = child(spec, 'type')
        declaration = _node_receipt(owner, spec)
        if typ.type == 'struct_type':
            fields = []
            listing = next(n for n in typ.named_children if n.type == 'field_declaration_list')
            for field in listing.named_children:
                if field.type == 'comment':
                    continue
                field_type = child(field, 'type')
                names = [n for n in field.named_children if n.type == 'field_identifier']
                if not names:
                    raise ValueError('embedded_options_field_unsupported')
                resolved = self.resolve(owner, owner.text(field_type), seen + (key,))
                if resolved['kind'] not in {'string', 'bool'}:
                    raise ValueError('options_field_type_unsupported')
                for name_node in names:
                    field_name = owner.text(name_node)
                    if not field_name[0].isupper():
                        raise ValueError('options_field_not_public')
                    fields.append(dict(name=field_name, type=resolved['kind'],
                                       declaration=_node_receipt(owner, field)))
            if len({f['name'] for f in fields}) != len(fields):
                raise ValueError('options_field_ambiguous')
            return dict(kind='struct', fields=fields, declarations=[declaration])
        if typ.type not in {'type_identifier', 'qualified_type'}:
            raise ValueError('type_shape_unsupported')
        resolved = self.resolve(owner, owner.text(typ), seen + (key,))
        if spec.type != 'type_alias' and resolved['kind'] != 'struct':
            raise ValueError('defined_scalar_type_not_builtin_alias')
        return dict(resolved, declarations=[declaration, *resolved['declarations']])


def catalog(corpus, issue, frontend=None):
    result = dict(version=VERSION, status='language_unsupported', language=corpus['language'], functions={}, pairs=[], evidence=[],
                  rejected_functions=[], type_binding_basis='frontend.module_resolution.go_modules plus repository declarations')
    if issue:
        public_issue = issue_contract(issue, max_chars=None)
        terminal_workflow = '\n\nIMPORTANT: Please work on this in a new branch from main and commit everything when you are done.'
        if public_issue.rstrip().endswith(terminal_workflow):
            public_issue = public_issue.rstrip()[:-len(terminal_workflow)].rstrip()
        if public_issue:
            start = issue.encode().find(public_issue.encode())
            assert start >= 0
            result['evidence'].append(receipt('issue.md', issue, start, start+len(public_issue.encode())))
    if corpus['language'] != 'go':
        return result
    directory = _Directory(corpus, frontend)
    for key, definitions in sorted(directory.functions.items()):
        if len(definitions) != 1 or not key[-1][0].isupper():
            continue
        source, node = definitions[0]
        try:
            if child(node, 'type_parameters') is not None:
                raise ValueError('generic_function_unsupported')
            parameters = _types(source, child(node, 'parameters'))
            results = _types(source, child(node, 'result'))
            if len(parameters) not in {1, 2, 3} or len(results) != 1:
                continue
            resolved = [directory.resolve(source, typ) for typ in parameters]
            kinds = [typ['kind'] for typ in resolved]
            result_kind = directory.resolve(source, results[0])['kind']
            options = None
            if kinds == ['string'] and result_kind == 'int':
                role = 'measure'
            elif (len(kinds) in {2, 3} and kinds.count('string') == 1
                  and kinds.count('int') == 1 and kinds.count('struct') == len(kinds)-2
                  and result_kind == 'string'):
                role = 'transform'
                options = kinds.index('struct') if 'struct' in kinds else None
                if options is not None and not re.fullmatch(r'[A-Za-z_]\w*', parameters[options]):
                    raise ValueError('options_type_must_have_local_named_binding')
            else:
                continue
            body = child(node, 'body')
            if body is None:
                raise ValueError('declaration_has_no_body')
            docs = _public_docs(source, node)
            identifier = f'{source.path}:{node.start_point.row+1}:{key[-1]}'
            row = dict(name=key[-1], package=list(_package(source)), parameters=parameters,
                       results=results, parameter_kinds=kinds, role=role,
                       declaration=_node_receipt(source, node),
                       public_header=receipt(source.path, source.code, node.start_byte, body.start_byte),
                       public_docs=[docs] if docs else [], options_fields=resolved[options]['fields'] if options is not None else [],
                       type_declarations=[decl for typ in resolved for decl in typ['declarations']])
            result['functions'][identifier] = row
            result['evidence'].append(row['public_header'])
            if docs:
                result['evidence'].append(docs)
        except (ValueError, StopIteration) as exc:
            result['rejected_functions'].append(dict(path=source.path, name=key[-1], reason=str(exc)))
    for transform_id, transform in result['functions'].items():
        if transform['role'] != 'transform':
            continue
        kinds = transform['parameter_kinds']
        for measure_id, measure in result['functions'].items():
            if measure['role'] == 'measure' and measure['package'] == transform['package']:
                result['pairs'].append(dict(transform=transform_id, measure=measure_id,
                    string_parameter=kinds.index('string'), bound_parameter=kinds.index('int'),
                    options_parameter=kinds.index('struct') if 'struct' in kinds else None))
    result['status'] = 'source_pairs' if result['pairs'] else 'no_supported_function_pairs'
    return result


def _verify_evidence(record, corpus, issue, available):
    if set(record) != {'path', 'source_sha256', 'start_byte', 'end_byte', 'text'}:
        raise ValueError('invalid_evidence_fields')
    path = record['path']
    if not any(doc['path'] == path and doc['start_byte'] <= record['start_byte']
               and record['end_byte'] <= doc['end_byte'] for doc in available['evidence']):
        raise ValueError('evidence_not_public_header_or_documentation')
    if path == 'issue.md':
        code = issue
    else:
        row = corpus['sources'].get(path)
        if not row or row.get('origin') != 'repository':
            raise ValueError('evidence_not_repository_source')
        code = row['code']
    start, end = record['start_byte'], record['end_byte']
    if (type(start) is not int or type(end) is not int or not 0 <= start < end <= len(code.encode())
            or receipt(path, code, start, end) != record or not record['text'].strip()):
        raise ValueError('evidence_source_mismatch')


def validate_relation(record, corpus, issue, frontend=None, *, available=None):
    if set(record) != {'id', 'law', 'unit', 'transform', 'measure', 'evidence', 'semantic_status'}:
        raise ValueError('invalid_relation_fields')
    if (not isinstance(record['id'], str) or not record['id'] or record['law'] != LAW
            or record['semantic_status'] != 'hypothesis_pending_independent_audit'
            or not isinstance(record['unit'], str) or not record['unit'].strip()
            or len(record['unit']) > 80 or '\n' in record['unit']):
        raise ValueError('unsupported_relation_law_unit_or_status')
    available = catalog(corpus, issue, frontend) if available is None else available
    if not isinstance(record['evidence'], list) or not record['evidence']:
        raise ValueError('missing_public_contract_evidence')
    for evidence in record['evidence']:
        _verify_evidence(evidence, corpus, issue, available)
    transform, measure = record['transform'], record['measure']
    if (set(transform) != {'declaration', 'string_parameter', 'bound_parameter', 'options_parameter'}
            or set(measure) != {'declaration'}):
        raise ValueError('invalid_function_binding_fields')
    rows = {}
    for role, binding in [('transform', transform), ('measure', measure)]:
        matches = [(key, row) for key, row in available['functions'].items()
                   if row['declaration'] == binding['declaration'] and row['role'] == role]
        if len(matches) != 1:
            raise ValueError('function_declaration_or_signature_unresolved')
        rows[role] = matches[0]
    matched = [pair for pair in available['pairs'] if pair['transform'] == rows['transform'][0]
               and pair['measure'] == rows['measure'][0]]
    if len(matched) != 1:
        raise ValueError('functions_not_same_package_pair')
    for field in ['string_parameter', 'bound_parameter', 'options_parameter']:
        value = transform[field]
        if ((value is not None and type(value) is not int) or value != matched[0][field]):
            raise ValueError('function_parameter_role_mismatch')
    return dict(record=record, transform=rows['transform'][1], measure=rows['measure'][1], pair=matched[0])


def _function(source, test):
    span = test['span']
    matches = [n for n in source.root.named_children if n.type == 'function_declaration'
               and (n.start_byte, n.end_byte) == (span['start_byte'], span['end_byte'])]
    if len(matches) != 1:
        raise ValueError('test_span_not_exact_function')
    return matches[0]


def _bindings(source, function):
    out = set()
    for node in walk(function):
        if node.type in {'short_var_declaration', 'range_clause'}:
            left = child(node, 'left')
            if left is not None:
                out.update(source.text(n) for n in left.named_children if n.type == 'identifier')
        elif node.type in {'var_spec', 'const_spec', 'type_spec', 'type_alias', 'parameter_declaration'}:
            typ = child(node, 'type')
            for name in node.named_children:
                if name == typ:
                    break
                if name.type in {'identifier', 'type_identifier'}:
                    out.add(source.text(name))
    return out


def _host_scope(source, function, relation, directory):
    if any(alias == '.' for alias in source.imports):
        raise ValueError('dot_import_scope_unsupported')
    parameters = child(function, 'parameters')
    declarations = parameters.named_children
    if len(declarations) != 1 or declarations[0].type != 'parameter_declaration':
        raise ValueError('test_parameter_unsupported')
    parameter = declarations[0]
    typ = source.text(child(parameter, 'type'))
    names = [n for n in parameter.named_children if n != child(parameter, 'type')]
    if len(names) != 1 or names[0].type != 'identifier' or source.text(names[0]) == '_':
        raise ValueError('test_parameter_binding_unsupported')
    tester = source.text(names[0])
    aliases = [alias for alias, target in source.imports.items() if target[0] == 'testing' and alias not in {'.', '_'}]
    if len(aliases) != 1 or typ != '*' + aliases[0] + '.T':
        raise ValueError('test_parameter_is_not_testing_T')
    block = child(function, 'body')
    listing = next((n for n in block.named_children if n.type == 'statement_list'), block)
    if any(n.type not in {'comment', 'short_var_declaration', 'assignment_statement',
                          'expression_statement', 'var_declaration', 'const_declaration'}
           for n in listing.named_children):
        raise ValueError('parent_test_is_not_straight_line')
    if any(n.type in {'go_statement', 'defer_statement', 'return_statement', 'func_literal',
                      'goto_statement', 'labeled_statement'} for n in walk(block)):
        raise ValueError('parent_test_has_delayed_or_nonlocal_control_flow')
    for node in walk(block):
        if node.type == 'selector_expression':
            field = source.text(child(node, 'field'))
            if field in {'Skip', 'Skipf', 'SkipNow', 'Fatal', 'Fatalf', 'FailNow', 'Parallel', 'Cleanup', 'Run', 'Goexit', 'Exit'}:
                raise ValueError('parent_test_has_termination_or_deferred_effect')
        if node.type == 'call_expression' and source.text(child(node, 'function')) == 'panic':
            raise ValueError('parent_test_has_unconditional_panic')
    bound = _bindings(source, function)
    names_required = {relation['transform']['name'], relation['measure']['name'], 'string', 'int', 'false', 'true'}
    index = relation['pair']['options_parameter']
    if index is not None:
        names_required.add(relation['transform']['parameters'][index])
    if bound & names_required or _bindings(source, block) & {tester}:
        raise ValueError('generated_expression_binding_shadowed')
    for node in walk(block):
        if node.type == 'assignment_statement':
            left = child(node, 'left')
            if left is not None and any(n.type == 'identifier' and source.text(n) == tester for n in left.named_children):
                raise ValueError('test_parameter_reassigned')
    if any(name in source.imports for name in names_required):
        raise ValueError('generated_expression_import_shadowed')
    if names_required & directory.test_names[_package(source)]:
        raise ValueError('generated_expression_test_package_binding_shadowed')
    package_names = directory.names[_package(source)]
    if package_names & {'string', 'int', 'false', 'true'}:
        raise ValueError('predeclared_scalar_binding_shadowed')
    return tester, block


def _literals(corpus, files):
    output, seen = [], set()
    tests = sorted(corpus['tests'].items(), key=lambda item: (item[1]['span']['path'], item[1]['span']['start_byte']))
    for base, test in tests:
        source = files.get(test['span']['path'])
        if source is None or not source.path.endswith('_test.go'):
            continue
        try:
            function = _function(source, test)
        except ValueError:
            continue
        for node in walk(child(function, 'body')):
            if node.type not in {'raw_string_literal', 'interpreted_string_literal'}:
                continue
            text = source.text(node)
            contents = text[1:-1]
            if (any(not 0x20 <= ord(char) <= 0x7e for char in contents)
                    or (node.type == 'interpreted_string_literal' and '\\' in contents)):
                continue
            if len(text.encode()) > MAX_LITERAL_BYTES or text in seen:
                continue
            seen.add(text)
            output.append(dict(expression=text, declaration=_node_receipt(source, node), source_test_id=base))
            if len(output) == MAX_STRINGS:
                return output
    return output


def _options(relation, literals):
    position = relation['pair']['options_parameter']
    if position is None:
        return [dict(expression=None, fields={})]
    name = relation['transform']['parameters'][position]
    rows = [dict(expression=name + '{}', fields={})]
    for field in relation['transform']['options_fields']:
        values = [row['expression'] for row in literals] if field['type'] == 'string' else ['false', 'true']
        for value in values:
            rows.append(dict(expression=name + '{' + field['name'] + ': ' + value + '}',
                             fields={field['name']: value}))
            if len(rows) == MAX_OPTIONS:
                return rows
    return rows


def _construct(base, source, function, tester, block, relation, literals, options):
    suffix = digest([VERSION, base, relation['record'], options])[:10]
    names = {key: '_quantity_' + key + '_' + suffix for key in ['input', 'bound', 'output', 'measured']}
    identifiers = {source.text(n) for n in walk(source.root) if n.type in {'identifier', 'type_identifier'}}
    if identifiers & set(names.values()):
        raise ValueError('generated_local_binding_collision')
    pair = relation['pair']
    arguments = [''] * len(relation['transform']['parameters'])
    arguments[pair['string_parameter']] = names['input']
    arguments[pair['bound_parameter']] = names['bound']
    if pair['options_parameter'] is not None:
        arguments[pair['options_parameter']] = options['expression']
    string_values = ', '.join(row['expression'] for row in literals)
    expression = relation['transform']['name'] + '(' + ', '.join(arguments) + ')'
    appended = '\n\t{\n'
    appended += f'\t\tfor _, {names["input"]} := range []string{{{string_values}}} {{\n'
    appended += f'\t\t\tfor _, {names["bound"]} := range []int{{1, 2, 4, 8}} {{\n'
    appended += f'\t\t\t\t{names["output"]} := {expression}\n'
    appended += f'\t\t\t\t{names["measured"]} := {relation["measure"]["name"]}({names["output"]})\n'
    appended += f'\t\t\t\tif {names["measured"]} > {names["bound"]} {{\n'
    appended += f'\t\t\t\t\t{tester}.Fatalf("quantity bound violated: input=%q bound=%d measured=%d", {names["input"]}, {names["bound"]}, {names["measured"]})\n'
    appended += '\t\t\t\t}\n\t\t\t}\n\t\t}\n\t}\n'
    position = block.end_byte - 1
    assert source.data[position:position+1] == b'}'
    edit = dict(span=dict(path=source.path, start_byte=position, end_byte=position,
                          start_line=block.end_point.row+1, end_line=block.end_point.row+1),
                before='', after=appended, role='observer')
    return dict(id='quantity_' + digest([VERSION, base, edit, relation['record']])[:24],
                base_test_id=base, source_test_ids=[base],
                imports=[], edits=[edit], generator=VERSION, operator='public_quantity_upper_bound',
                kind='source_bound_contract_property', oracle_status='public_contract_hypothesis_pending_full_audit',
                source_evidence=dict(relation=relation['record'], source_literals=literals,
                                     option_configuration=options, bounds=list(BOUNDS),
                                     transform_call_upper_bound=len(literals)*len(BOUNDS),
                                     measure_call_upper_bound=len(literals)*len(BOUNDS),
                                     complete_original_test_preserved=True,
                                     repeated_calls_may_have_effects=True,
                                     semantic_obligations_pending=POLICY['semantic_obligations']))


def generate(corpus, frontend, issue, ir, *, limit=16):
    result = dict(version=VERSION, status='language_unsupported', candidates=[], total_candidates=0,
                  skipped=[], rejected_relations=[], relations_accepted=0)
    result['rejected'] = result['rejected_relations']
    if corpus['language'] != 'go':
        return result
    if set(ir) != {'version', 'relations'} or ir['version'] != IR_VERSION:
        raise ValueError('unsupported_relation_ir')
    if type(limit) is not int or limit < 0:
        raise ValueError('invalid_candidate_limit')
    available = catalog(corpus, issue, frontend)
    directory = _Directory(corpus, frontend)
    literals = _literals(corpus, directory.files)
    result['source_literals'] = literals
    relations = []
    for record in ir['relations']:
        try:
            relations.append(validate_relation(record, corpus, issue, frontend, available=available))
        except (ValueError, KeyError, TypeError, IndexError) as exc:
            result['rejected_relations'].append(dict(id=record.get('id'), reason=str(exc)))
    relations.sort(key=lambda r: (r['transform']['declaration']['path'], r['transform']['declaration']['start_byte'],
                                 r['measure']['declaration']['path'], r['measure']['declaration']['start_byte'], digest(r['record'])))
    result['relations_accepted'] = len(relations)
    if not literals:
        result['status'] = 'no_repository_test_string_literals'
        return result
    tests = sorted(corpus['tests'].items(), key=lambda item: (item[1]['span']['path'], item[1]['span']['start_byte']))
    candidates = []
    for relation in relations:
        host = None
        for base, test in tests:
            source = directory.files.get(test['span']['path'])
            if source is None or list(_package(source)) != relation['transform']['package']:
                continue
            try:
                function = _function(source, test)
                tester, block = _host_scope(source, function, relation, directory)
                host = (base, source, function, tester, block)
                break
            except ValueError as exc:
                result['skipped'].append(dict(base_test_id=base, relation_id=relation['record']['id'], reason=str(exc)))
        if host is None:
            result['skipped'].append(dict(relation_id=relation['record']['id'], reason='no_supported_same_package_host_test'))
            continue
        for options in _options(relation, literals):
            try:
                candidates.append(_construct(*host, relation, literals, options))
            except ValueError as exc:
                result['skipped'].append(dict(base_test_id=host[0], relation_id=relation['record']['id'], reason=str(exc)))
    unique = {candidate['id']: candidate for candidate in candidates}
    result.update(status='source_candidates', total_candidates=len(unique), candidates=list(unique.values())[:limit])
    return result
