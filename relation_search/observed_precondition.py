"""Complete a declared producer/consumer contract with an observed value.

This module constructs tests; it does not discover or prove natural-language
contracts. A relation record names declarations and exact public evidence.
Its semantic implication remains a hypothesis for independent full-test audit.
The first implementation supports adjacent Go error guards and local receivers.
"""
from __future__ import annotations

import hashlib
import json
import posixpath
import re

from anchor_retrieval.syntax import Source, attr_parts, call_parts, child, walk

VERSION = 'observed-precondition-go.v1'
IR_VERSION = 'observed-precondition-relation.v1'
LAW = 'producer_success_implies_consumer_success'
POLICY = dict(version=VERSION, language='go',
    relation=LAW,
    generation='Insert a consumer of the observed result immediately after the existing fatal producer-error guard, on the same local receiver.',
    unchanged='Complete original test, original producer arguments, all original assertions and cleanup.',
    evidence='Exact issue/source quotations and source declaration receipts; implication requires independent semantic audit.',
    semantic_obligations=['The contract must guarantee success, not merely permit an input; environmental failures remain possible.',
                          'The consumer must preserve every subsequent source-test expectation; textual preservation does not prove this.',
                          'Adjacent statements do not exclude asynchronous aliases outside the test.',
                          'A timeout alone does not establish a functional defect.'],
    deadline='A fixed five-second Context bounds waiting calls; original tests must already use the Context method. Deadline expiry alone is not a correctness proof.',
    forbidden_inputs=['audit labels', 'historical candidates', 'reference implementations', 'hidden tests'],
    limitations=['Go only; two-result zero-argument producer and one-error-result consumer',
                 'same-package named concrete receiver with a source-declared constructor return type',
                 'adjacent require.NoError guard from testify; no intervening operations',
                 'consumer arguments are one observed value and optionally one bounded Context',
                 'unknown effects and natural-language implication are not statically proved'])

# This is a reviewable input specification, not a JSON-schema validation library.
IR_SCHEMA = {
    'version': IR_VERSION,
    'relations': [{
        'id': 'discovery-assigned identifier',
        'law': LAW,
        'same_receiver': True,
        'evidence': [{'path': 'issue.md or repository source path',
                      'source_sha256': 'SHA256 of complete UTF-8 source',
                      'start_byte': 0, 'end_byte': 1, 'text': 'exact public quotation'}],
        'producer': {'declaration': 'same receipt shape, spanning one complete Go method',
                     'value_result': 0, 'error_result': 1},
        'consumer': {'declaration': 'same receipt shape, spanning one complete Go method',
                     'arguments': [{'kind': 'bounded_context'},
                                   {'kind': 'observed_value'}]},
        'semantic_status': 'hypothesis_pending_independent_audit',
    }],
}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def receipt(path, code, start_byte, end_byte):
    data = code.encode()
    return dict(path=path, source_sha256=hashlib.sha256(data).hexdigest(),
                start_byte=start_byte, end_byte=end_byte, text=data[start_byte:end_byte].decode())


def _span(source, node):
    return dict(path=source.path, start_byte=node.start_byte, end_byte=node.end_byte,
                line=node.start_point.row+1, end_line=node.end_point.row+1)


def _exact(source, record):
    node = source.root.named_descendant_for_byte_range(record['start_byte'], record['end_byte']-1)
    while node is not None:
        if (node.start_byte, node.end_byte) == (record['start_byte'], record['end_byte']):
            return node
        node = node.parent
    raise ValueError('receipt_does_not_span_one_syntax_node')


def _verify_receipt(record, corpus, issue, *, allow_issue=False):
    required = {'path', 'source_sha256', 'start_byte', 'end_byte', 'text'}
    if set(record) != required:
        raise ValueError('invalid_receipt_fields')
    if record['path'] == 'issue.md' and allow_issue:
        code = issue
    else:
        row = corpus['sources'].get(record['path'])
        if not row or row.get('origin') != 'repository':
            raise ValueError('receipt_is_not_repository_source')
        code = row['code']
    data = code.encode()
    start, end = record['start_byte'], record['end_byte']
    if (type(start) is not int or type(end) is not int or not 0 <= start < end <= len(data)
            or hashlib.sha256(data).hexdigest() != record['source_sha256']
            or data[start:end].decode() != record['text']):
        raise ValueError('receipt_source_mismatch')
    return code


def _package(source):
    package = next((n for n in source.root.named_children if n.type == 'package_clause'), None)
    return (posixpath.dirname(source.path), source.text(package).removeprefix('package').strip())


def _types(source, node):
    if node is None:
        return []
    if node.type != 'parameter_list':
        return [source.text(node)]
    out = []
    for declaration in node.named_children:
        if declaration.type != 'parameter_declaration':
            raise ValueError('unsupported_parameter_shape')
        typ = child(declaration, 'type')
        names = [n for n in declaration.named_children if n != typ]
        out.extend([source.text(typ)] * max(1, len(names)))
    return out


def _canonical_type(source, text):
    if text.startswith('*'):
        return '*' + _canonical_type(source, text[1:])
    if '.' in text:
        alias, name = text.split('.', 1)
        return source.imports.get(alias, (alias,))[0]+'::'+name
    return text


def _method(record, corpus, issue, files):
    code = _verify_receipt(record, corpus, issue)
    source = files.setdefault(record['path'], Source(record['path'], code, 'go'))
    if source.root.has_error:
        raise ValueError('declaration_source_parse_error')
    node = _exact(source, record)
    if node.type != 'method_declaration' or node.parent != source.root:
        raise ValueError('declaration_is_not_top_level_method')
    receivers = _types(source, child(node, 'receiver'))
    if len(receivers) != 1 or not re.fullmatch(r'\*?[A-Za-z_]\w*', receivers[0]):
        raise ValueError('receiver_type_not_simple_named_type')
    return dict(source=source, node=node, name=source.text(child(node, 'name')),
                receiver=receivers[0].lstrip('*'), package=_package(source),
                parameters=_types(source, child(node, 'parameters')),
                results=_types(source, child(node, 'result')))


def validate_relation(record, corpus, issue, files=None):
    files = {} if files is None else files
    if set(record) != {'id', 'law', 'same_receiver', 'evidence', 'producer', 'consumer', 'semantic_status'}:
        raise ValueError('invalid_relation_fields')
    if (not isinstance(record['id'], str) or not record['id'] or record['law'] != LAW
            or record['same_receiver'] is not True
            or record['semantic_status'] != 'hypothesis_pending_independent_audit'):
        raise ValueError('unsupported_relation_law_or_status')
    if not record['evidence']:
        raise ValueError('missing_public_contract_evidence')
    for evidence in record['evidence']:
        _verify_receipt(evidence, corpus, issue, allow_issue=True)
    producer, consumer = record['producer'], record['consumer']
    if set(producer) != {'declaration', 'value_result', 'error_result'} or set(consumer) != {'declaration', 'arguments'}:
        raise ValueError('invalid_method_binding_fields')
    p = _method(producer['declaration'], corpus, issue, files)
    c = _method(consumer['declaration'], corpus, issue, files)
    if p['receiver'] != c['receiver'] or p['package'] != c['package']:
        raise ValueError('producer_consumer_owner_types_differ')
    value, error = producer['value_result'], producer['error_result']
    if (type(value) is not int or type(error) is not int or {value, error} != {0, 1}
            or p['parameters'] or len(p['results']) != 2 or p['results'][error] != 'error'
            or c['results'] != ['error']):
        raise ValueError('unsupported_producer_or_consumer_signature')
    arguments = consumer['arguments']
    if len(arguments) != len(c['parameters']) or len(arguments) not in {1, 2}:
        raise ValueError('consumer_argument_count_mismatch')
    kinds = [a.get('kind') for a in arguments]
    if kinds.count('observed_value') != 1 or kinds.count('bounded_context') != len(kinds)-1:
        raise ValueError('unsupported_consumer_arguments')
    context = False
    for argument, typ in zip(arguments, c['parameters']):
        if argument['kind'] == 'observed_value':
            if set(argument) != {'kind'} or _canonical_type(p['source'], p['results'][value]) != _canonical_type(c['source'], typ):
                raise ValueError('observed_value_type_mismatch')
        else:
            if set(argument) != {'kind'} or _canonical_type(c['source'], typ) != 'context::Context':
                raise ValueError('context_parameter_type_mismatch')
            context = True
    return dict(record=record, producer=p, consumer=c, value=value, error=error, bounded_context=context)


def _statements(function):
    block = child(function, 'body')
    listing = next((n for n in block.named_children if n.type == 'statement_list'), block)
    return [n for n in listing.named_children if n.type != 'comment']


def _writes(function, source, name):
    writes = []
    for node in walk(function):
        left = child(node, 'left', 'name') if node.type in {
            'short_var_declaration', 'assignment_statement', 'var_spec', 'range_clause'} else None
        if node.type in {'inc_statement', 'dec_statement'}:
            left = node
        if left is not None:
            writes.extend(n for n in walk(left) if n.type == 'identifier' and source.text(n) == name)
    return writes


def _shadowed(function, source, name):
    parameters = child(function, 'parameters')
    return bool(_writes(function, source, name) or any(
        source.text(n) == name for declaration in parameters.named_children
        for n in declaration.named_children if n != child(declaration, 'type')))


def _receiver_type(source, function, name, before, files):
    writes = _writes(function, source, name)
    if len(writes) != 1 or writes[0].start_byte >= before:
        raise ValueError('receiver_binding_not_unique_local')
    declaration = writes[0].parent
    if declaration.type == 'expression_list':
        declaration = declaration.parent
    if declaration.type != 'short_var_declaration' or declaration not in _statements(function):
        raise ValueError('receiver_definition_not_direct_local_statement')
    left, right = child(declaration, 'left'), child(declaration, 'right')
    values = list(right.named_children)
    if len(values) != 1 or values[0].type != 'call_expression':
        raise ValueError('receiver_origin_not_source_constructor_call')
    call = values[0]
    fn, args = call_parts(call)
    if fn.type != 'identifier':
        raise ValueError('receiver_constructor_not_same_package_function')
    ctor = source.text(fn)
    if _shadowed(function, source, ctor):
        raise ValueError('receiver_constructor_shadowed')
    if ctor == 'new' and len(args) == 1 and args[0].type in {'identifier', 'type_identifier'}:
        return source.text(args[0])
    definitions = [(s, n) for s in files.values() if _package(s) == _package(source)
                   for n in s.root.named_children if n.type == 'function_declaration'
                   and s.text(child(n, 'name')) == ctor]
    if len(definitions) != 1:
        raise ValueError('receiver_constructor_declaration_not_unique')
    src, node = definitions[0]
    results = _types(src, child(node, 'result'))
    slot = list(left.named_children).index(writes[0])
    if slot >= len(results) or not re.fullmatch(r'\*?[A-Za-z_]\w*', results[slot]):
        raise ValueError('receiver_constructor_result_type_unknown')
    return results[slot].lstrip('*')


def _guard(source, function, statement, error):
    if statement.type != 'expression_statement' or len(statement.named_children) != 1:
        raise ValueError('producer_guard_not_adjacent_fatal_assertion')
    call = statement.named_children[0]
    if call.type != 'call_expression':
        raise ValueError('producer_guard_not_adjacent_fatal_assertion')
    fn, args = call_parts(call)
    owner, field = attr_parts(fn)
    if (owner is None or owner.type != 'identifier' or source.text(field) != 'NoError'
            or source.imports.get(source.text(owner), (None,))[0] != 'github.com/stretchr/testify/require'
            or len(args) != 2 or args[0].type != 'identifier' or args[1].type != 'identifier'
            or source.text(args[1]) != error or _shadowed(function, source, source.text(owner))):
        raise ValueError('producer_guard_not_adjacent_fatal_assertion')
    return fn, args


def _consumer_donor(relation, files, corpus):
    """Recover a typed original-test invocation, not just a matching method name."""
    for base, test in sorted(corpus['tests'].items()):
        source = files.get(test['span']['path'])
        if source is None or _package(source) != relation['consumer']['package']:
            continue
        try:
            function = _exact(source, test['span'])
        except ValueError:
            continue
        if function.type != 'function_declaration':
            continue
        for call in walk(function):
            if call.type != 'call_expression':
                continue
            fn, args = call_parts(call)
            receiver, field = attr_parts(fn)
            if (receiver is None or receiver.type != 'identifier'
                    or source.text(field) != relation['consumer']['name']
                    or len(args) != len(relation['consumer']['parameters'])):
                continue
            try:
                if _receiver_type(source, function, source.text(receiver), call.start_byte, files) != relation['consumer']['receiver']:
                    continue
            except ValueError:
                continue
            return dict(test=base, call=receipt(source.path, source.code, call.start_byte, call.end_byte))
    raise ValueError('consumer_has_no_typed_original_test_donor')


def _construct(source, function, statement, following, relation, files, corpus, base):
    left, right = child(statement, 'left'), child(statement, 'right')
    names, values = list(left.named_children), list(right.named_children)
    if len(names) != 2 or len(values) != 1 or values[0].type != 'call_expression':
        return None
    call = values[0]
    fn, args = call_parts(call)
    receiver, field = attr_parts(fn)
    if (receiver is None or receiver.type != 'identifier' or source.text(field) != relation['producer']['name'] or args):
        return None
    if any(n.type != 'identifier' or source.text(n) == '_' for n in names):
        raise ValueError('producer_result_binding_unsupported')
    obj = source.text(receiver)
    if _package(source) != relation['producer']['package'] or _receiver_type(source, function, obj, statement.start_byte, files) != relation['producer']['receiver']:
        raise ValueError('producer_receiver_type_unproved')
    value, error = source.text(names[relation['value']]), source.text(names[relation['error']])
    if len(_writes(function, source, value)) != 1:
        raise ValueError('observed_value_binding_not_unique')
    guard_fn, guard_args = _guard(source, function, following, error)
    # Closures or goroutines can change the receiver between lexical statements.
    if any(n.type in {'go_statement', 'func_literal'} for n in walk(function)):
        raise ValueError('concurrent_or_captured_test_scope')
    bounded_context = relation['bounded_context']
    existing = {source.text(n) for n in walk(source.root) if n.type == 'identifier'}
    suffix = digest([base, statement.start_byte, relation['record']])[:10]
    ctx, cancel = '_observedCtx_'+suffix, '_observedCancel_'+suffix
    if {ctx, cancel} & existing:
        raise ValueError('generated_binding_collision')
    prefix, test_ids = [], [base]
    if bounded_context:
        aliases = {}
        for module in ['context', 'time']:
            matches = [name for name, target in source.imports.items() if target[0] == module]
            if len(matches) != 1 or matches[0] in {'.', '_'} or _shadowed(function, source, matches[0]):
                raise ValueError('required_standard_import_missing_or_shadowed')
            aliases[module] = matches[0]
        prefix = [f"{ctx}, {cancel} := {aliases['context']}.WithTimeout({aliases['context']}.Background(), 5 * {aliases['time']}.Second)",
                  f'defer {cancel}()']
    test_ids = list(dict.fromkeys([base, relation['donor']['test']]))
    arguments = [value if a['kind'] == 'observed_value' else ctx for a in relation['record']['consumer']['arguments']]
    consumer = f"{obj}.{relation['consumer']['name']}({', '.join(arguments)})"
    check = f'{source.text(guard_fn)}({source.text(guard_args[0])}, {consumer})'
    before = source.text(following)
    indent = re.search(r'[^\n]*$', source.data[:following.start_byte].decode()).group()
    indent = indent if not indent.strip() else '\t'
    after = before + '\n' + '\n'.join(indent+line for line in [*prefix, check])
    edit = dict(span=_span(source, following), before=before, after=after, role='observer')
    return dict(id='observed_'+digest([VERSION, base, edit, relation['record']])[:24],
                base_test_id=base, source_test_ids=test_ids, edits=[edit], imports=[],
                generator=VERSION, kind='observed_precondition', operator='consume_observed_value',
                oracle_status='contract_implication_pending_independent_full_test_audit',
                source_evidence=dict(relation=relation['record'], producer=_span(source, call),
                    producer_error_guard=_span(source, following), receiver=obj, value_binding=value,
                    consumer_source_donor=relation['donor'],
                    same_local_receiver=True, no_intervening_operation=True,
                    complete_original_test_preserved=True,
                    semantic_obligations_pending=POLICY['semantic_obligations'],
                    context_scaffold='standard-library five-second execution bound' if bounded_context else None))


def generate(corpus, frontend, issue, relation_ir, *, limit=4):
    result = dict(version=VERSION, status='language_unsupported', candidates=[], total_candidates=0,
                  skipped=[], rejected_relations=[], relations_accepted=0)
    if corpus['language'] != 'go':
        return result
    if set(relation_ir) != {'version', 'relations'} or relation_ir['version'] != IR_VERSION:
        raise ValueError('unsupported_relation_ir')
    files = {}
    for path, row in corpus['sources'].items():
        if row.get('origin') != 'repository' or row.get('language', 'go') != 'go':
            continue
        if frontend.get('sources', {}).get(path, {}).get('code') != row['code']:
            raise ValueError('frontend_source_mismatch:'+path)
        source = Source(path, row['code'], 'go')
        if not source.root.has_error:
            files[path] = source
    relations = []
    for record in relation_ir['relations']:
        try:
            validated = validate_relation(record, corpus, issue, files)
            validated['donor'] = _consumer_donor(validated, files, corpus)
            relations.append(validated)
        except (ValueError, KeyError, TypeError, IndexError) as exc:
            result['rejected_relations'].append(dict(id=record.get('id'), reason=str(exc)))
    result['relations_accepted'] = len(relations)
    candidates = []
    for base, test in sorted(corpus['tests'].items(), key=lambda x: (x[1].get('retrieval_rank') or 100000, x[1]['span']['path'], x[1]['span']['start_byte'])):
        source = files.get(test['span']['path'])
        if source is None:
            continue
        try:
            function = _exact(source, test['span'])
        except ValueError:
            continue
        if function.type != 'function_declaration' or function.parent != source.root:
            continue
        statements = _statements(function)
        for statement, following in zip(statements, statements[1:]):
            if statement.type != 'short_var_declaration':
                continue
            for relation in relations:
                try:
                    candidate = _construct(source, function, statement, following, relation, files, corpus, base)
                    if candidate:
                        candidates.append(candidate)
                except (ValueError, IndexError) as exc:
                    result['skipped'].append(dict(base_test_id=base, relation_id=relation['record']['id'],
                                                  statement=_span(source, statement), reason=str(exc)))
    unique = {candidate['id']: candidate for candidate in candidates}
    result.update(status='source_candidates', total_candidates=len(unique), candidates=list(unique.values())[:limit])
    return result
