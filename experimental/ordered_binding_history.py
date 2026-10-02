"""Experimental local binding histories, not heap aliases or execution traces.

Only source-local definitions and direct call operands are related. Rebinding
creates a new ID; branches, nested scopes and unsupported updates are barriers.
Opaque arguments may escape and opaque calls may mutate state. No output value,
guest-language meaning, oracle truth or physical object identity is inferred.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import time

from anchor_retrieval.syntax import ATTRS, CALLS, FUNCTIONS, Source, attr_parts, call_parts, child, walk
from relation_search.instrument import _program_edits

VERSION = 'experimental-ordered-local-bindings.v4'
SCOPES = FUNCTIONS | {'arrow_function', 'function_expression', 'func_literal', 'lambda', 'class_definition', 'class_declaration'}
BARRIERS = SCOPES | {
    'if_statement', 'for_statement', 'while_statement', 'try_statement', 'with_statement',
    'switch_statement', 'select_statement', 'expression_switch_statement', 'type_switch_statement',
    'match_statement', 'conditional_expression', 'ternary_expression', 'boolean_operator',
    'list_comprehension', 'dictionary_comprehension', 'set_comprehension', 'generator_expression',
    'await', 'await_expression', 'yield', 'yield_expression', 'go_statement', 'defer_statement',
    'return_statement', 'raise_statement', 'throw_statement', 'break_statement', 'continue_statement',
    'global_statement', 'nonlocal_statement', 'delete_statement', 'named_expression',
    'update_expression', 'inc_statement', 'dec_statement', 'optional_chain',
    'import_statement', 'import_from_statement', 'for_in_statement', 'do_statement',
    'goto_statement', 'labeled_statement', 'fallthrough_statement',
}
ASSIGNMENTS = {'assignment', 'assignment_expression', 'augmented_assignment', 'augmented_assignment_expression', 'assignment_statement', 'short_var_declaration', 'variable_declarator', 'var_spec'}
LISTS = {'expression_list', 'pattern_list'}
LIMITATIONS = [
    'definition IDs identify lexical local binding versions, not physical object or heap-state identity; reflective rebinding is not resolved',
    'call order is lexical nesting/source order, conditional on reaching and completing preceding evaluation',
    'arguments and receiver calls may escape or mutate state; state values and callee effects are not inferred',
    'opaque Get calls, attribute/subscript reads, copied values and distinct aliases are never merged',
    'branch, loop, callback, nested update and exception-region histories are incomplete and explicitly unknown',
    'helper observations are retained without inventing dynamic invocation phases',
    'facts neither establish test validity nor infer expected outputs or guest-language semantics',
]


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _ref(source, node):
    return dict(path=source.path, start_byte=node.start_byte, end_byte=node.end_byte,
                start_line=node.start_point.row + 1, end_line=node.end_point.row + 1, version='modified')


def _contains(outer, inner):
    return (outer['path'] == inner['path'] and outer['start_byte'] <= inner['start_byte']
            and inner['end_byte'] <= outer['end_byte'])


def _bare(node):
    while node is not None and node.type == 'parenthesized_expression' and len(node.named_children) == 1:
        node = node.named_children[0]
    return node if node is not None and node.type == 'identifier' else None


def _items(node):
    return list(node.named_children) if node is not None and node.type in LISTS else ([node] if node is not None else [])


def _in_root_scope(node, root):
    cursor = node.parent
    while cursor is not None:
        if cursor.type in SCOPES:
            return cursor == root
        cursor = cursor.parent
    return False


def _body_statements(root):
    body = child(root, 'body')
    if body is None or body.type not in {'block', 'statement_block'}:
        raise ValueError('root block body unavailable')
    if len(body.named_children) == 1 and body.named_children[0].type == 'statement_list':
        body = body.named_children[0]
    return [n for n in body.named_children if n.type != 'comment']


def _call_postorder(node):
    if node.type in SCOPES:
        return
    for part in node.named_children:
        yield from _call_postorder(part)
    if node.type in CALLS:
        yield node


def _assignments(statement):
    node = statement
    if node.type == 'expression_statement' and len(node.named_children) == 1:
        node = node.named_children[0]
    if node.type in ASSIGNMENTS:
        return [node]
    if node.type in {'lexical_declaration', 'variable_declaration', 'var_declaration'}:
        return [n for n in node.named_children if n.type in ASSIGNMENTS]
    return []


def analyze_source(code, language, *, path='test.py', root_ref=None, root_name=None,
                   parameter_names=None, observations=None, max_nodes=20000):
    """Return lexical facts for one root. Supplied observations are source refs.

    `observations` rows contain id/ref/is_root. Non-root Qs remain visible but
    their runtime phases stay unknown. No framework names identify observations.
    """
    result = dict(version=VERSION, status='unknown', source_sha256=sha(code.encode()),
                  language=language, bindings=[], calls=[], statements=[], groups=[], observations=[],
                  unknowns=[], limitations=LIMITATIONS, semantic_validity='unassessed')
    result['observations'] = [dict(id=q['id'], ref=q['ref'], phase_statement=None,
                                  phase_status='source_analysis_unavailable', lexical_calls_before_or_inside_site=[])
                              for q in observations or []]
    try:
        source = Source(path, code, language)
        if source.root.has_error:
            raise ValueError('source_parse_error')
        nodes = list(walk(source.root))
        roots = [n for n in nodes if n.type in SCOPES | {'decorated_definition'} | CALLS and (
            (_ref(source, n)['start_byte'] == root_ref['start_byte'] and n.end_byte == root_ref['end_byte'])
            if root_ref else source.text(child(n, 'name')) == root_name)]
        if len(roots) != 1:
            raise ValueError('root_not_unique')
        wrapper = root = roots[0]
        if root.type == 'decorated_definition':
            choices = [n for n in root.named_children if n.type in FUNCTIONS]
            if len(choices) != 1:
                raise ValueError('decorated_root_not_unique')
            root = choices[0]
            result['unknowns'].append(dict(reason='root_decorator_behavior_unproved',ref=_ref(source,wrapper)))
        elif root.type in CALLS:
            # The caller supplies a fixed-test source extent. Recover its one
            # direct callback syntactically; no test-framework name heuristic.
            _, args = call_parts(root)
            choices = [n for n in args if n.type in SCOPES and child(n,'body') is not None]
            if len(choices) != 1:
                raise ValueError('root_callback_not_unique')
            root = choices[0]
        if sum(1 for _ in walk(root)) > max_nodes:
            raise ValueError('root_node_budget_exceeded')
        result['root'] = _ref(source, wrapper)
        result['binding_scope'] = _ref(source, root)
        params = child(root, 'parameters')
        syntactic_parameters = {source.text(n) for n in walk(params) if n.type == 'identifier'} if params else set()
        parameter_names = set(parameter_names or ()) | syntactic_parameters
        external = {source.text(n) for declaration in walk(root)
                    if declaration.type in {'global_statement','nonlocal_statement'}
                    for n in walk(declaration) if n.type == 'identifier'}
        # A nested scope may rebind a captured variable later. This intentionally
        # overapproximates captures rather than solving closure scope/escapes.
        captured = {source.text(n) for scope in walk(root) if scope != root and scope.type in SCOPES
                    for n in walk(scope) if n.type == 'identifier'}
        addressed = {source.text(_bare(child(n,'operand','argument'))) for n in walk(root)
                     if language == 'go' and n.type == 'unary_expression'
                     and source.text(child(n,'operator')) == '&'
                     and _bare(child(n,'operand','argument')) is not None}
        excluded = parameter_names | external | captured | addressed
        result['excluded_parameter_bindings'] = sorted(parameter_names)
        result['excluded_external_bindings'] = sorted(external)
        result['excluded_possible_capture_bindings'] = sorted(captured)
        result['excluded_address_taken_bindings'] = sorted(addressed)
        if external or captured or addressed:
            result['unknowns'].append(dict(reason='external_capture_or_address_taken_bindings_excluded',ref=_ref(source,root)))
        env, local_names, bindings = {}, set(), result['bindings']
        observations = list(observations or [])
        if not observations and language == 'python':
            observations = [dict(id='A' + str(i), ref=_ref(source, node), is_root=_in_root_scope(node,root))
                            for i, node in enumerate(n for n in walk(root) if n.type == 'assert_statement')]

        def unknown(reason, node, statement_id):
            result['unknowns'].append(dict(reason=reason, ref=_ref(source, node), statement=statement_id))

        def calls_in(node, statement_id, usable):
            for call in _call_postorder(node):
                fn, args = call_parts(call)
                operands = []
                direct = _bare(fn)
                if direct is not None:
                    operands.append(('callee', direct, None))
                elif fn is not None and fn.type in ATTRS:
                    receiver, _ = attr_parts(fn)
                    if _bare(receiver) is not None:
                        operands.append(('receiver', _bare(receiver), None))
                for slot, arg in enumerate(n for n in args if n.type != 'comment'):
                    value = child(arg, 'value') if arg.type == 'keyword_argument' else arg
                    if _bare(value) is not None:
                        operands.append(('input', _bare(value), slot))
                uses = []
                for role, operand, slot in operands:
                    name = source.text(operand)
                    if usable and name in env:
                        uses.append(dict(binding=env[name], role=role, slot=slot, ref=_ref(source, operand),
                                         escape='possible_opaque_argument_escape' if role == 'input' else 'effects_unknown'))
                result['calls'].append(dict(id='C' + str(len(result['calls'])), ref=_ref(source, call),
                    callee=source.text(fn), statement=statement_id, uses=uses,
                    order='lexical_postorder_not_execution_trace', binding_status='resolved_local_versions' if usable else 'unknown_control_or_update'))

        for index, statement in enumerate(_body_statements(root)):
            ident = 'S' + str(index)
            row = dict(id=ident, ref=_ref(source, statement), call_ids=[], definitions=[])
            result['statements'].append(row)
            before_calls = len(result['calls'])
            all_nodes = list(walk(statement))
            blocked = next((n for n in all_nodes if n.type in BARRIERS
                            or (n.type == 'binary_expression' and source.text(child(n, 'operator')) in {'&&', '||', '??'})
                            or (n.type == 'unary_expression' and source.text(child(n, 'operator')) == '&')), None)
            assignments = _assignments(statement)
            nested = [n for n in all_nodes if n.type in ASSIGNMENTS and n not in assignments]
            # Conditional evaluation of a Python assertion's diagnostic expression.
            if statement.type == 'assert_statement' and len(statement.named_children) > 1:
                blocked = statement
            if blocked is not None or nested:
                unknown('control_scope_escape_or_nested_update', blocked or nested[0], ident)
                env.clear()
                calls_in(statement, ident, False)
            elif assignments:
                for assignment in assignments:
                    left = child(assignment, 'left', 'name')
                    right = child(assignment, 'right', 'value')
                    lhs, rhs = _items(left), _items(right)
                    if not lhs or any(n.type != 'identifier' for n in lhs) or len({source.text(n) for n in lhs}) != len(lhs):
                        calls_in(assignment, ident, False)
                        unknown('non_simple_or_duplicate_assignment_targets', assignment, ident)
                        env.clear()
                        continue
                    # Evaluate every RHS before simultaneous targets are installed.
                    calls_in(right, ident, True) if right is not None else None
                    old_env = dict(env)
                    for slot, target in enumerate(lhs):
                        name = source.text(target)
                        if name in excluded or (language == 'go' and name == '_'):
                            continue
                        if language != 'python':
                            if assignment.type in {'short_var_declaration','variable_declarator','var_spec'}:
                                local_names.add(name)
                            elif name not in local_names:
                                unknown('assignment_to_unproved_local_binding',target,ident)
                                continue
                        binding_id = 'B' + str(len(bindings))
                        value = rhs[slot] if len(lhs) == len(rhs) else right
                        operator = source.text(child(assignment, 'operator'))
                        alias = _bare(value) if (operator in {'', '=', ':='} and 'augmented' not in assignment.type) else None
                        row_binding = dict(id=binding_id, name=name, definition=_ref(source, target),
                            assignment=_ref(source, assignment), statement=ident,
                            previous_definition=old_env.get(name), rhs=_ref(source, value) if value is not None else None,
                            rhs_result_slot=slot if len(lhs) != len(rhs) else None,
                            direct_rhs_binding=old_env.get(source.text(alias)) if alias is not None else None,
                            identity='local_definition_version_only')
                        bindings.append(row_binding); row['definitions'].append(binding_id); env[name] = binding_id
                        if row_binding['direct_rhs_binding']:
                            unknown('alias_or_value_copy_not_merged', assignment, ident)
            else:
                calls_in(statement, ident, True)
            row['call_ids'] = [c['id'] for c in result['calls'][before_calls:]]

        result['observations'] = []
        for observation in observations:
            ref = observation['ref']
            statement = next((r for r in result['statements'] if _contains(r['ref'], ref)), None) if observation.get('is_root') else None
            calls = [c['id'] for c in result['calls'] if c['ref']['end_byte'] <= ref['end_byte']] if statement else []
            result['observations'].append(dict(id=observation['id'], ref=ref,
                phase_statement=statement['id'] if statement else None,
                lexical_calls_before_or_inside_site=calls,
                phase_status='root_lexical_site_not_dynamic_reachability' if statement else 'helper_or_unmapped_phase_unknown'))
        for binding in bindings:
            uses = [dict(call=c['id'], roles=[u for u in c['uses'] if u['binding'] == binding['id']])
                    for c in result['calls'] if any(u['binding'] == binding['id'] for u in c['uses'])]
            if len(uses) < 2:
                continue
            first, last = (int(uses[i]['call'][1:]) for i in (0, -1))
            result['groups'].append(dict(binding=binding['id'], uses=uses,
                interval_call_ids=[c['id'] for c in result['calls'][first:last + 1]],
                state_equality='not_inferred', heap_identity='not_inferred',
                opaque_argument_escape=any(r['role'] == 'input' for u in uses for r in u['roles'])))
        result['status'] = 'partial' if result['unknowns'] else 'source_facts_available'
    except (ValueError, KeyError, TypeError, AttributeError) as error:
        result['unknowns'].append(dict(reason=str(error)))
    return result


def analyze(corpus, frontend, candidate, *, source_analysis):
    """Reuse frozen compact Q identities; revalidate only modified owner bytes."""
    selected = corpus['tests'][candidate['base_test_id']]
    path = selected['span']['path']; original = corpus['sources'][path]['code'].encode()
    edits = sorted(_program_edits(candidate), key=lambda e: (e['span']['start_byte'], e['span']['end_byte']))
    previous = -1
    for edit in edits:
        at = edit['span']
        if (not _contains(selected['span'], at) or at['start_byte'] < previous
                or original[at['start_byte']:at['end_byte']].decode() != edit['before']):
            raise ValueError('candidate_edit_source_mismatch')
        previous = at['end_byte']
    modified = original
    for edit in reversed(edits):
        at = edit['span']; modified = modified[:at['start_byte']] + edit['after'].encode() + modified[at['end_byte']:]
    graph = source_analysis
    def absolute(ref):
        block = graph['sources'][ref['source']]
        text = block['code'].encode()[ref['start']:ref['end']]
        at = dict(path=block['path'], start_byte=block['start_byte'] + ref['start'], end_byte=block['start_byte'] + ref['end'], version='modified')
        if at['path'] == path and modified[at['start_byte']:at['end_byte']] != text:
            raise ValueError('compact_source_ref_mismatch')
        return at
    root = graph['units'][graph['root']]
    observations = [dict(id=ident, ref=absolute(row['at']), is_root=row['unit'] == graph['root'])
                    for ident, row in graph.get('obligations', {}).items()]
    result = analyze_source(modified.decode(), corpus['language'], path=path, root_ref=absolute(root['at']),
        parameter_names=[p['name'] for p in root['parameters']], observations=observations)
    result['candidate_id'] = candidate['id']
    result['original_source_sha256'] = sha(original)
    if candidate.get('imports'):
        result['unknowns'].append(dict(reason='candidate_added_imports_effects_unproved')); result['status'] = 'partial'
    return result


def census(prepared_paths, output):
    """Read prepared SOURCE inputs and analysis only, never decisions or outcomes."""
    output = Path(output); output.mkdir(parents=True, exist_ok=False)
    module_sha = sha(Path(__file__).read_bytes()); started = time.monotonic(); rows = []; cache = {}
    receipts = []
    for prepared_path in prepared_paths:
        prepared_path = Path(prepared_path); raw = prepared_path.read_bytes(); prepared = json.loads(raw)
        if prepared['scope'] not in {'positive', 'development'}:
            raise ValueError('scope must be fixed positive or development source inventory')
        receipts.append(dict(path=str(prepared_path), sha256=sha(raw), scope=prepared['scope']))
        for item in prepared['items']:
            inputs = {}
            for kind in ('corpus', 'candidates'):
                receipt = item['source_inputs'][kind]; path = receipt['path']
                if path not in cache:
                    blob = Path(path).read_bytes(); cache[path] = (sha(blob), json.loads(blob))
                digest, inputs[kind] = cache[path]
                if digest != receipt['sha256']:
                    raise ValueError('source_input_sha_mismatch')
            candidate = next(c for c in inputs['candidates'] if c['id'] == item['candidate_id'])
            analysis_path = Path(item['analysis_path']); analysis_raw = analysis_path.read_bytes()
            graph = json.loads(analysis_raw)['analysis']
            # This owner-only analysis does not use the potentially large frontend.
            result = analyze(inputs['corpus'], None, candidate, source_analysis=graph)
            name = 'item_' + str(len(rows)).zfill(4) + '.json'
            (output / name).write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
            rows.append(dict(case=item['case'], candidate_id=item['candidate_id'], source_inventory=prepared['scope'],
                status=result['status'], groups=len(result['groups']), calls=len(result['calls']),
                observations=len(result['observations']), unknown_phases=sum(q['phase_statement'] is None for q in result['observations']),
                unknowns=len(result['unknowns']), artifact=name,
                source_inputs={k:item['source_inputs'][k] for k in ('corpus','frontend','candidates')},
                compact_source_analysis=dict(path=str(analysis_path), sha256=sha(analysis_raw))))
    if sha(Path(__file__).read_bytes()) != module_sha:
        raise ValueError('module_changed_during_census')
    summary = dict(version=VERSION, module_sha256=module_sha, source_inventories=receipts,
        provider_calls=0, native_executions=0, labels_or_decisions_read=False, outcomes_read=False,
        elapsed_seconds=round(time.monotonic()-started,3), items=len(rows),
        with_repeated_local_bindings=sum(r['groups'] > 0 for r in rows), total_groups=sum(r['groups'] for r in rows),
        statuses=dict(Counter(r['status'] for r in rows)), rows=rows, limitations=LIMITATIONS)
    (output / 'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
    return {k:v for k,v in summary.items() if k != 'rows'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prepared', action='append', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(census(args.prepared,args.output),indent=2))
