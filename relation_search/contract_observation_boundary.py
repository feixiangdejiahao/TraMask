"""Move a source observation across a contractually invisible boundary.

TypeScript prototype: an adjacent zero-argument boundary statement and
expect(receiver.method(args)).toBe(primitive). A relation authorizes the exact
receiver-origin pattern. Names alone never connect two receiver bindings.
Natural-language conditions remain independently auditable hypotheses.
"""
from __future__ import annotations

from collections import Counter
import hashlib
import json
import posixpath
import re

from anchor_retrieval.syntax import Source, attr_parts, call_parts, child, literal, walk
from relation_search.observed_precondition import receipt, _verify_receipt

VERSION = 'contract-observation-boundary-typescript.v1'
IR_VERSION = 'contract-observation-boundary-relation.v1'
LAW = 'boundary_preserves_scalar_observation'
CONDITIONS = [
    'observation_is_defined_before_and_after',
    'observation_is_repeatable_and_read_only',
    'boundary_preserves_this_observation',
    'owner_is_isolated_from_external_concurrent_mutation',
    'receiver_sharing_through_owner_methods_is_within_contract_scope',
    'additional_observations_preserve_original_suffix_validity',
]
POLICY = dict(version=VERSION, language='typescript', law=LAW,
    construction='Save Q before adjacent B; retain B and the complete original test; append equality after the original scalar assertion.',
    source_pattern='Zero-argument B method; direct Q receiver method; expect(Q).toBe(boolean/number/string literal).',
    identity='Lexically resolved const bindings; same binding or a receiver directly constructed by a method of the boundary owner; matching imported owner factory.',
    alias_scope='Reject direct test aliases, rebindings, captured receivers, and receiver escapes outside owner-method calls. Library aliasing remains a contract condition.',
    primitive_domain='Only execute the new equality when the saved result has the literal expected primitive type; unsupported domains are missed, not defect reports.',
    limitations=['No Python, callbacks, field projections, non-null assertions, deep copies, async or conditional boundary statements.',
                 'The contract conditions are supplied hypotheses, not inferred truth from AST checks.',
                 'Source controls do not prove the original oracle or added read purity.',
                 'Same owner-method templates do not prove heap isolation; independent full-test audit is required.'],
    forbidden_inputs=['evaluation labels', 'historical candidate programs', 'reference implementations', 'hidden tests'])


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def _span(source, node):
    return dict(path=source.path, start_byte=node.start_byte, end_byte=node.end_byte,
                line=node.start_point.row+1, end_line=node.end_point.row+1)


def _exact(source, extent):
    node = source.root.named_descendant_for_byte_range(extent['start_byte'], extent['end_byte']-1)
    while node is not None:
        if (node.start_byte, node.end_byte) == (extent['start_byte'], extent['end_byte']):
            return node
        node = node.parent
    raise ValueError('source_extent_not_one_syntax_node')


def _chain(source, node):
    if node.type == 'identifier':
        return [source.text(node)]
    if node.type == 'member_expression':
        owner, member = attr_parts(node)
        if owner is not None and member is not None and member.type == 'property_identifier':
            return _chain(source, owner)+[source.text(member)]
    raise ValueError('computed_optional_or_nonidentifier_receiver')


def _callback(source, extent):
    registration = _exact(source, extent)
    if registration.type == 'expression_statement' and len(registration.named_children) == 1:
        registration = registration.named_children[0]
    if registration.type != 'call_expression':
        raise ValueError('test_registration_not_direct_call')
    _, arguments = call_parts(registration)
    functions = [n for n in arguments if n.type in {'arrow_function', 'function_expression'}]
    if len(functions) != 1:
        raise ValueError('test_callback_not_unique')
    root = functions[0]
    body = child(root, 'body')
    if body is None or body.type != 'statement_block' or any(n.type == 'async' for n in root.children):
        raise ValueError('unsupported_test_callback_body')
    return root, [n for n in body.named_children if n.type != 'comment']


def _scope_declarations(scope):
    declarations = []
    for node in scope.named_children:
        if node.type in {'lexical_declaration', 'variable_declaration'}:
            declarations.extend(n for n in node.named_children if n.type == 'variable_declarator')
    return declarations


def _resolve(source, name, at):
    """Resolve nearest lexical declaration before use; no name-only fallback."""
    cursor = at
    while cursor is not None:
        if cursor.type in {'statement_block', 'program'}:
            matches = [n for n in _scope_declarations(cursor)
                       if source.text(child(n, 'name')) == name]
            if matches:
                if len(matches) != 1 or matches[0].start_byte >= at.start_byte:
                    raise ValueError('binding_ambiguous_or_not_available_at_entry')
                declaration = matches[0]
                if not source.text(declaration.parent).lstrip().startswith('const '):
                    raise ValueError('binding_is_not_const')
                return dict(key=(source.path, declaration.start_byte), name=name, node=declaration,
                            value=child(declaration, 'value'), kind='const')
        if cursor.type in {'arrow_function', 'function_expression', 'function_declaration'}:
            parameters = child(cursor, 'parameters')
            if parameters is not None and any(source.text(n) == name for n in walk(parameters) if n.type == 'identifier'):
                raise ValueError('parameter_binding_not_supported')
        cursor = cursor.parent
    if name in source.imports:
        module, imported = source.imports[name]
        if module.startswith('.'):
            module = posixpath.normpath(posixpath.join(posixpath.dirname(source.path), module))
        return dict(key=('import', module, imported), name=name, kind='import', canonical=[module, imported])
    raise ValueError('binding_origin_unresolved')


def _constant_argument(source, node, entry):
    if node.type in {'true', 'false', 'number', 'string', 'null'}:
        return None
    if node.type == 'identifier':
        return _resolve(source, source.text(node), entry)
    raise ValueError('observer_argument_requires_call_or_unknown_expression')


def _primitive(source, node):
    if node.type in {'true', 'false'}:
        return 'boolean'
    if node.type == 'number' and re.fullmatch(r'\d+(?:\.\d+)?', source.text(node)):
        return 'number'
    if node.type == 'string':
        value = literal(source.text(node))
        if isinstance(value, str):
            return 'string'
    raise ValueError('postcondition_expected_value_not_closed_primitive')


def _assertion(source, statement):
    if statement.type != 'expression_statement' or len(statement.named_children) != 1:
        raise ValueError('postcondition_not_expression_statement')
    assertion = statement.named_children[0]
    if assertion.type != 'call_expression':
        raise ValueError('postcondition_not_call')
    fn, arguments = call_parts(assertion)
    if fn.type != 'member_expression':
        raise ValueError('postcondition_not_direct_toBe')
    expect_call, matcher = attr_parts(fn)
    if source.text(matcher) != 'toBe' or len(arguments) != 1 or expect_call.type != 'call_expression':
        raise ValueError('postcondition_not_direct_toBe')
    expect_fn, observed = call_parts(expect_call)
    if expect_fn.type != 'identifier' or len(observed) != 1:
        raise ValueError('postcondition_expect_not_direct')
    binding = _resolve(source, source.text(expect_fn), expect_fn)
    if (binding['kind'] != 'import' or binding['canonical'][0] not in {'vitest', '@jest/globals'}
            or binding['canonical'][1] != 'expect'):
        raise ValueError('expect_import_not_resolved')
    actual = observed[0]
    if actual.type != 'call_expression':
        raise ValueError('observation_is_not_direct_method_call')
    q_fn, q_args = call_parts(actual)
    path = _chain(source, q_fn)
    if len(path) != 2:
        raise ValueError('observation_receiver_not_local_identifier')
    return dict(actual=actual, path=path, arguments=q_args, expect=expect_fn,
                scalar_kind=_primitive(source, arguments[0]))


def _call_statement(source, statement):
    if statement.type != 'expression_statement' or len(statement.named_children) != 1:
        raise ValueError('boundary_not_direct_statement')
    call = statement.named_children[0]
    if call.type != 'call_expression':
        raise ValueError('boundary_not_call')
    fn, arguments = call_parts(call)
    if arguments:
        raise ValueError('boundary_has_arguments')
    path = _chain(source, fn)
    if len(path) < 2:
        raise ValueError('boundary_not_receiver_method')
    return call, path


def _root_of_call(source, call):
    try:
        fn, _ = call_parts(call)
        return _chain(source, fn)[0]
    except ValueError:
        return None


def _check_uses(source, root, bindings, owner):
    keys = {binding['key'] for binding in bindings if binding['kind'] == 'const'}
    names = {binding['name'] for binding in bindings}
    for node in walk(root):
        if node.type in {'await_expression', 'yield_expression'}:
            raise ValueError('async_test_execution')
        if node != root and node.type in {'arrow_function', 'function_expression', 'function_declaration'}:
            raise ValueError('nested_callback_scope')
        if node.type not in {'identifier', 'shorthand_property_identifier', 'shorthand_property_identifier_pattern'} or source.text(node) not in names:
            continue
        # Declaration targets are not uses. Every remaining use resolves to its
        # own lexical definition, including names reused in distinct scopes.
        if node.parent.type == 'variable_declarator' and child(node.parent, 'name') == node:
            continue
        resolved = _resolve(source, source.text(node), node)
        if resolved['key'] not in keys:
            continue
        parent = node.parent
        while parent is not None and parent.type in {'member_expression', 'parenthesized_expression'}:
            if parent.type == 'member_expression' and child(parent, 'object') != node and node.parent == parent:
                break
            parent = parent.parent
        # Receiver use must end in a direct method invocation. A reference
        # copied into a variable, object, property or closure is rejected.
        if node.parent.type == 'member_expression' and parent is not None and parent.type == 'call_expression':
            fn, _ = call_parts(parent)
            if fn.start_byte <= node.start_byte < node.end_byte <= fn.end_byte:
                continue
        if node.parent.type == 'arguments' and node.parent.parent.type == 'call_expression':
            call = node.parent.parent
            first = _root_of_call(source, call)
            if first is not None:
                try:
                    call_owner = _resolve(source, first, call)
                    if call_owner['key'] == owner['key']:
                        continue
                except ValueError:
                    pass
        raise ValueError('receiver_alias_rebinding_or_escape')


def _opportunity(source, root, before, after, base):
    boundary, b_path = _call_statement(source, before)
    q = _assertion(source, after)
    owner = _resolve(source, b_path[0], before)
    observer = _resolve(source, q['path'][0], before)
    if owner['kind'] != 'const' or observer['kind'] != 'const':
        raise ValueError('receiver_must_be_local_const')
    root_body = child(root, 'body')
    if owner['node'].parent.parent != root_body or observer['node'].parent.parent != root_body:
        raise ValueError('receiver_not_owned_by_test_scope')
    init = owner['value']
    if init is None or init.type != 'call_expression':
        raise ValueError('owner_not_created_by_direct_imported_factory')
    factory, factory_args = call_parts(init)
    if factory.type != 'identifier' or factory_args:
        raise ValueError('owner_factory_requires_zero_arguments')
    factory_binding = _resolve(source, source.text(factory), factory)
    if factory_binding['kind'] != 'import':
        raise ValueError('owner_factory_is_not_imported')
    creator = None
    if observer['key'] == owner['key']:
        ownership = dict(kind='same_binding', creator_path=[])
    else:
        creator = observer['value']
        if creator is None or creator.type != 'call_expression':
            raise ValueError('observer_receiver_not_created_by_owner')
        creator_fn, _ = call_parts(creator)
        creator_path = _chain(source, creator_fn)
        if len(creator_path) < 2 or _resolve(source, creator_path[0], creator)['key'] != owner['key']:
            raise ValueError('observer_receiver_belongs_to_different_owner')
        ownership = dict(kind='created_by_owner', creator_path=creator_path[1:])
    argument_bindings = [_constant_argument(source, argument, before) for argument in q['arguments']]
    _check_uses(source, root, [owner, observer], owner)
    # Observe before B only with exactly the same argument bindings used after B.
    for argument, binding in zip(q['arguments'], argument_bindings):
        if binding is not None and _resolve(source, source.text(argument), argument)['key'] != binding['key']:
            raise ValueError('observer_argument_binding_changes_across_boundary')
    pattern = dict(boundary_path=b_path[1:], observer_method=q['path'][1],
                   observer_arity=len(q['arguments']), scalar_kind=q['scalar_kind'],
                   owner_factory=factory_binding['canonical'], owner_relation=ownership)
    refs = dict(boundary=receipt(source.path, source.code, boundary.start_byte, boundary.end_byte),
                observation=receipt(source.path, source.code, q['actual'].start_byte, q['actual'].end_byte),
                owner_factory=receipt(source.path, source.code, init.start_byte, init.end_byte),
                owner_creator=receipt(source.path, source.code, creator.start_byte, creator.end_byte) if creator else None)
    return dict(id='boundary_source_'+digest([base, refs, pattern])[:24], base_test_id=base,
                pattern=pattern, examples=refs,
                binding_evidence=dict(owner_definition=_span(source, owner['node']),
                    observer_definition=_span(source, observer['node']),
                    argument_definitions=[_span(source, b['node']) if b and b['kind'] == 'const' else b['canonical'] if b else None for b in argument_bindings],
                    same_bindings_before_and_after=True, direct_test_aliases_and_escapes='excluded',
                    library_aliasing='requires_public_owner_scope_contract'),
                before_statement=_span(source, before), after_statement=_span(source, after),
                expect_callee=source.text(q['expect']))


def catalog(corpus, frontend):
    result = dict(version=VERSION, status='language_unsupported', opportunities=[], rejected=[],
                  repository_tests=0, adjacent_statement_pairs=0)
    if corpus['language'] != 'typescript':
        return result
    files = {}
    for base, test in sorted(corpus['tests'].items(), key=lambda row: (row[1].get('retrieval_rank') or 100000, row[1]['span']['path'], row[1]['span']['start_byte'])):
        path = test['span']['path']; row = corpus['sources'][path]
        if row.get('origin') != 'repository':
            continue
        result['repository_tests'] += 1
        if frontend.get('sources', {}).get(path, {}).get('code') != row['code']:
            raise ValueError('frontend_source_mismatch:'+path)
        if path not in files:
            files[path] = Source(path, row['code'], 'typescript')
        source = files[path]
        if source.root.has_error:
            result['rejected'].append(dict(base_test_id=base, reason='source_parse_error')); continue
        try:
            root, statements = _callback(source, test['span'])
        except ValueError as exc:
            result['rejected'].append(dict(base_test_id=base, reason=str(exc))); continue
        for before, after in zip(statements, statements[1:]):
            # Restrict diagnostics to pairs ending in a source assertion. This
            # is an inventory operation, never a semantic admission decision.
            if not re.match(r'\s*(?:expect|\w+)\s*\(', source.text(after)):
                continue
            result['adjacent_statement_pairs'] += 1
            try:
                result['opportunities'].append(_opportunity(source, root, before, after, base))
            except ValueError as exc:
                result['rejected'].append(dict(base_test_id=base, boundary=_span(source, before), reason=str(exc)))
    result['status'] = 'source_catalog'
    result['rejection_counts'] = dict(sorted(Counter(row['reason'] for row in result['rejected']).items()))
    result['total_opportunities'] = len(result['opportunities'])
    return result


def relation_template(opportunity, evidence, *, identifier='r1'):
    """Construct a schema example; semantic conditions are unproved hypotheses."""
    return dict(id=identifier, law=LAW, source_pattern=opportunity['pattern'],
                examples=opportunity['examples'], evidence=evidence,
                conditions={key: True for key in CONDITIONS},
                semantic_status='hypothesis_pending_independent_audit')


def validate_relation(record, corpus, issue, source_catalog):
    if set(record) != {'id', 'law', 'source_pattern', 'examples', 'evidence', 'conditions', 'semantic_status'}:
        raise ValueError('invalid_relation_fields')
    if (not isinstance(record['id'], str) or not record['id'] or record['law'] != LAW
            or record['semantic_status'] != 'hypothesis_pending_independent_audit'
            or record['conditions'] != {key: True for key in CONDITIONS}):
        raise ValueError('unsupported_law_or_unmet_semantic_conditions')
    if not record['evidence']:
        raise ValueError('public_contract_evidence_missing')
    for row in record['evidence']:
        _verify_receipt(row, corpus, issue, allow_issue=True)
    for row in record['examples'].values():
        if row is not None:
            _verify_receipt(row, corpus, issue)
    matches = [row for row in source_catalog['opportunities']
               if row['pattern'] == record['source_pattern'] and row['examples'] == record['examples']]
    if len(matches) != 1:
        raise ValueError('relation_examples_do_not_match_one_checked_source_opportunity')
    return record


def generate(corpus, frontend, issue, relation_ir, *, limit=4):
    source_catalog = catalog(corpus, frontend)
    result = dict(version=VERSION, status=source_catalog['status'], candidates=[], total_candidates=0,
                  rejected_relations=[], source_catalog=source_catalog)
    if corpus['language'] != 'typescript':
        return result
    if set(relation_ir) != {'version', 'relations'} or relation_ir['version'] != IR_VERSION:
        raise ValueError('unsupported_relation_ir')
    relations = []
    for record in relation_ir['relations']:
        try:
            relations.append(validate_relation(record, corpus, issue, source_catalog))
        except (ValueError, KeyError, TypeError) as exc:
            result['rejected_relations'].append(dict(id=record.get('id'), reason=str(exc)))
    candidates = []
    for opportunity in source_catalog['opportunities']:
        for relation in relations:
            if relation['source_pattern'] != opportunity['pattern']:
                continue
            path = opportunity['before_statement']['path']; code = corpus['sources'][path]['code']; data = code.encode()
            before, after = opportunity['before_statement'], opportunity['after_statement']
            original = data[before['start_byte']:after['end_byte']].decode()
            snapshot = '_boundaryObservation_'+digest([opportunity['id'], relation['id']])[:10]
            if re.search(r'\b'+re.escape(snapshot)+r'\b', code):
                continue
            q = opportunity['examples']['observation']['text']
            indent = re.search(r'[^\n]*$', data[:before['start_byte']].decode()).group()
            indent = indent if not indent.strip() else '    '
            kind = opportunity['pattern']['scalar_kind']; expect = opportunity['expect_callee']
            changed = f'const {snapshot} = {q};\n{indent}'+original
            changed += f'\n{indent}if (typeof {snapshot} === "{kind}") {{\n{indent}    {expect}({q}).toBe({snapshot});\n{indent}}}'
            span = dict(before, end_byte=after['end_byte'], end_line=after['end_line'])
            candidate = dict(id='boundary_'+digest([VERSION, opportunity['id'], relation, changed])[:24],
                base_test_id=opportunity['base_test_id'], source_test_ids=[opportunity['base_test_id']],
                generator=VERSION, kind='contract_observation_boundary', operator='scalar_snapshot_across_boundary',
                edits=[dict(span=span, before=original, after=changed, role='observer')], imports=[],
                oracle_status='contract_hypothesis_pending_independent_full_test_audit',
                source_evidence=dict(relation=relation, opportunity=opportunity,
                    complete_original_test_preserved=True, primitive_domain_guard=True,
                    nonprimitive_observation='new relation check skipped; no correctness claim',
                    semantic_conditions_proved_by_static_analysis=False))
            candidates.append(candidate)
    unique = {row['id']: row for row in candidates}
    result.update(status='source_candidates', total_candidates=len(unique), candidates=list(unique.values())[:limit])
    return result
