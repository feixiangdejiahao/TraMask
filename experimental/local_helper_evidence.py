"""Source-backed instances of simple helpers local to a modified test.

Resolve declarations in their lexical function scope, then bind each call's
arguments separately. Existing assertion adapters identify operand roles; no
helper or parameter name supplies a role. These are source facts, not inferred
expected values, execution traces, or a proof that changing a port is safe.
"""
from __future__ import annotations

from collections import Counter
import hashlib
import json

from anchor_retrieval.graph import Flow
from anchor_retrieval.index import Index
from anchor_retrieval.syntax import CALLS, FUNCTIONS, Unit, attr_parts, call_parts, child, walk
from experimental.go_assertion_helper import parameters as go_parameters
from generic_composition.corpus import _assertion_nodes, span
from relation_search.oracle_evidence import _modified_sources

VERSION = 'local-helper-evidence-v2'
FUNCTION_NODES = FUNCTIONS | {'func_literal', 'arrow_function', 'function_expression', 'lambda'}
CONTROL_NODES = {'if_statement', 'elif_clause', 'else_clause', 'for_statement', 'for_in_statement',
    'while_statement', 'switch_statement', 'expression_switch_statement', 'try_statement',
    'except_clause', 'catch_clause', 'with_statement', 'select_statement', 'conditional_expression',
    'ternary_expression'}
WRITES = {'assignment', 'augmented_assignment', 'assignment_statement', 'short_var_declaration',
    'variable_declarator', 'assignment_expression', 'augmented_assignment_expression', 'var_spec'}


def _id(*parts):
    return hashlib.sha256(json.dumps(parts, sort_keys=True).encode()).hexdigest()[:24]


def _function_scope(node):
    parent = node.parent
    while parent is not None and parent.type not in FUNCTION_NODES:
        parent = parent.parent
    return parent


def _scope(node, language):
    if language == 'python':
        return _function_scope(node)
    parent = node.parent
    while parent is not None and parent.type not in {'block','statement_block'} | FUNCTION_NODES:
        parent = parent.parent
    return parent


def _controlled(node, boundary):
    parent = node.parent
    while parent is not None and parent != boundary:
        if parent.type in CONTROL_NODES:
            return True
        parent = parent.parent
    return False


def _single(node):
    if node is not None and node.type == 'expression_list' and len(node.named_children) == 1:
        return node.named_children[0]
    return node


def _writes(source, node):
    if node.type in FUNCTIONS:
        name = child(node, 'name')
        return [source.text(name)] if name is not None else []
    if node.type not in WRITES:
        return []
    target = child(node, 'left', 'name')
    if target is None:
        return []
    targets = target.named_children if target.type in {'expression_list', 'pattern_list'} else [target]
    return [source.text(item) for item in targets if item.type == 'identifier']


def _parameters(source, function):
    parameters = child(function, 'parameters')
    if source.language == 'go':
        result = go_parameters(source, function)
        if result is None:
            return [], 'unsupported_parameters'
        names = [node for declaration in parameters.named_children
                 for node in declaration.named_children if node.type == 'identifier']
        return [dict(row, span=span(source, node)) for row, node in zip(result, names)], None
    if parameters is None:
        parameter = child(function, 'parameter')
        values = [parameter] if parameter is not None else []
    else:
        values = [node for node in parameters.named_children if node.type != 'comment']
        if any(node.type in {'positional_separator', 'keyword_separator'} for node in parameters.children):
            return [], 'unsupported_parameters'
    result = []
    for parameter in values:
        if parameter.type == 'identifier':
            name, typename = parameter, ''
        elif parameter.type in {'typed_parameter', 'required_parameter'}:
            name = child(parameter, 'name', 'pattern')
            if name is None:
                name = next((node for node in parameter.named_children if node.type == 'identifier'), None)
            typename = source.text(child(parameter, 'type'))
            if child(parameter, 'value') is not None:
                return [], 'unsupported_parameters'
        else:
            return [], 'unsupported_parameters'
        if name is None or name.type != 'identifier':
            return [], 'unsupported_parameters'
        result.append(dict(name=source.text(name), type=typename, span=span(source, name)))
    return result, None


def _declaration(source, node):
    if source.language == 'python' and node.type == 'function_definition':
        return child(node, 'name'), node
    if source.language == 'go' and node.type in {'short_var_declaration', 'var_spec'}:
        name, value = _single(child(node, 'left', 'name')), _single(child(node, 'right', 'value'))
        if value is not None and value.type == 'func_literal':
            return name, value
    if source.language == 'typescript' and node.type == 'variable_declarator':
        value = child(node, 'value')
        if value is not None and value.type in {'arrow_function', 'function_expression'}:
            return child(node, 'name'), value
    return None, None


def _owned_nodes(body):
    yield body
    for node in body.named_children:
        if node.type in FUNCTION_NODES:
            # The name binding belongs to this scope, not the nested body.
            yield node
        else:
            yield from _owned_nodes(node)


def _receiver_rebound(source, function, name):
    """Conservatively detect shadow/write in each enclosing lexical scope.

    No reachability claim: even a conditional write denies the candidate port.
    Nested bodies are separate scopes, but their declaration names still bind.
    """
    current = function
    while current is not None:
        parameters = child(current, 'parameters', 'parameter')
        if parameters is not None and any(node.type == 'identifier' and source.text(node) == name
                                          for node in walk(parameters)):
            return True
        body = child(current, 'body') if current != source.root else source.root
        if body is not None and any(name in _writes(source, node) for node in _owned_nodes(body)):
            return True
        current = _function_scope(current) if current != source.root else None
        if current is None and body != source.root:
            current = source.root
    return False


def _adapter_reason(source, helper, statement):
    if statement.type not in CALLS:
        return None  # Intrinsic Python assert / already adapted standard guard.
    callee, _ = call_parts(statement)
    if source.language == 'go':
        receiver, _ = attr_parts(callee) if callee is not None else (None, None)
        name = source.text(receiver)
        supported = {('github.com/stretchr/testify/require', None), ('github.com/stretchr/testify/assert', None)}
    elif source.language == 'typescript':
        expects = [node for node in walk(callee) if node.type in CALLS
                   and source.text(call_parts(node)[0]) == 'expect'] if callee is not None else []
        if len(expects) != 1:
            return 'assertion_adapter_import_unproved'
        name = source.text(call_parts(expects[0])[0])
        supported = {('vitest', 'expect'), ('@jest/globals', 'expect')}
    else:
        # A method spelled assertEqual can belong to any object. Direct assert
        # remains supported; unittest receiver types are not resolved here.
        return 'assertion_adapter_import_unproved'
    if _receiver_rebound(source, helper['function'], name):
        return 'assertion_adapter_rebound'
    if source.imports.get(name) not in supported:
        return 'assertion_adapter_import_unproved'
    return None


def _inside_class(node, boundary):
    current = node.parent
    while current is not None and current != boundary:
        if current.type in {'class_definition', 'class_declaration', 'class'}:
            return True
        current = current.parent
    return False


def _assertions(source, index, helper):
    function, params = helper['function'], helper['parameters']
    unit = Unit(source, function, child(function, 'body'), helper['name'], test=True)
    unit.params = [row['name'] for row in params]
    unit.param_types = {row['name']:row['type'] for row in params}
    flow = Flow(index, unit)
    # Capture in a nested function is also another use of the expected formal.
    # A shadowed same-spelling identifier conservatively denies a port too.
    uses = list(walk(unit.body))
    names = set(unit.params)
    rows = []
    for assertion in flow.assertions:
        statement, actual, expected, predicate = _assertion_nodes(source, assertion, unit)
        if statement is None:
            continue
        actual_roots = [node['id'] for node in flow.nodes if actual is not None
                        and node['start_byte'] == actual.start_byte and node['end_byte'] == actual.end_byte]
        deps = sorted({flow.nodes[node]['parameter'] for node in flow.slice(actual_roots)
                       if flow.nodes[node]['kind']=='parameter' and flow.nodes[node].get('parameter') in names})
        formal = source.text(expected) if expected is not None and expected.type == 'identifier' else None
        reason = None
        if formal not in names:
            reason = 'expected_is_not_bare_formal'
        elif any(node.type == 'identifier' and source.text(node) == formal
                 and (node.start_byte, node.end_byte) != (expected.start_byte, expected.end_byte) for node in uses):
            reason = 'expected_formal_has_other_uses'
        adapter_reason = _adapter_reason(source, helper, statement)
        if adapter_reason:
            reason = adapter_reason
        rows.append(dict(id=_id(helper['id'],span(source,statement)), span=span(source,statement),
            code=source.text(statement), observed=dict(code=source.text(actual),span=span(source,actual)) if actual else None,
            expected=dict(code=source.text(expected),span=span(source,expected)) if expected else None,
            predicate=predicate, assertion_adapter=assertion.assertion_adapter,
            observed_formal_dependencies=deps, expected_formal=formal if formal in names else None,
            expected_port_status='source_bound_candidate' if reason is None else 'unknown',
            expected_port_reason=reason, execution_status='lexical_only_not_execution_proof'))
    return rows


def analyze(corpus, candidate):
    """Analyze all local helper-name calls inside the complete modified test."""
    try:
        _, source, changes, _, source_unknowns = _modified_sources(corpus, candidate)
    except (ValueError, KeyError, TypeError, UnicodeError) as error:
        return dict(version=VERSION,candidate_id=candidate['id'],status='unknown',bindings=[],calls=[],
                    unknowns=[dict(reason='modified_source_unavailable',detail=str(error))])
    owner = corpus['tests'][candidate['base_test_id']]['span']
    lower = owner['start_byte']
    upper = owner['end_byte']+sum(len(row['after'].encode())-(row['original_span']['end_byte']-row['original_span']['start_byte']) for row in changes)
    nodes = [node for node in walk(source.root) if lower <= node.start_byte <= node.end_byte <= upper]
    if source.root.has_error:
        return dict(version=VERSION,candidate_id=candidate['id'],status='unknown',bindings=[],calls=[],
                    unknowns=[dict(reason='modified_source_parse_error')])
    source_sha = hashlib.sha256(source.data).hexdigest()
    helpers = []
    for declaration in nodes:
        name, function = _declaration(source,declaration)
        if name is None or function is None or name.type != 'identifier' or _function_scope(declaration) is None:
            continue
        parameters, reason = _parameters(source,function)
        body = child(function,'body')
        scope = _scope(declaration,source.language)
        if body is None or body.type not in {'block','statement_block'}:
            reason = 'helper_body_not_block'
        elif _inside_class(declaration,_function_scope(declaration)):
            reason = 'helper_declaration_in_class_scope'
        elif _controlled(declaration,_function_scope(declaration)):
            reason = 'helper_declaration_in_control_flow'
        elif function.parent is not None and function.parent.type=='decorated_definition':
            reason = 'decorated_helper'
        elif source.language=='python' and source.text(function).startswith('async '):
            reason = 'async_helper'
        elif any(set(_writes(source,node)) & {p['name'] for p in parameters} for node in _owned_nodes(body)):
            reason = 'formal_reassigned_or_shadowed'
        helper = dict(id=_id(source_sha,span(source,declaration)), name=source.text(name),
            declaration=declaration,function=function,scope=scope,parameters=parameters,reason=reason)
        helpers.append(helper)
    index = Index([source],'')
    for helper in helpers:
        other_writes = [node for node in nodes if node != helper['declaration']
                        and helper['name'] in _writes(source,node)]
        if other_writes:
            helper['reason'] = 'helper_reassigned_or_shadowed'
        helper['assertions'] = _assertions(source,index,helper) if helper['reason'] is None else []
    calls, unknowns = [], list(source_unknowns)
    helper_names = {helper['name'] for helper in helpers}
    for node in nodes:
        if node.type not in CALLS:
            continue
        callee, arguments = call_parts(node)
        if callee is None or callee.type != 'identifier' or source.text(callee) not in helper_names:
            continue
        matching = [helper for helper in helpers if helper['name']==source.text(callee)
                    and helper['scope']==_scope(node,source.language)]
        reason = None
        helper = matching[0] if len(matching)==1 else None
        if helper is None:
            reason = 'local_helper_binding_ambiguous_or_different_scope'
        elif helper['reason']:
            reason = helper['reason']
        elif node.start_byte < helper['declaration'].end_byte:
            reason = 'call_before_helper_definition'
        elif _controlled(node,_function_scope(node)):
            reason = 'helper_call_in_control_flow'
        elif any(argument.type in {'keyword_argument','list_splat','dictionary_splat','spread_element','variadic_argument'} for argument in arguments):
            reason = 'spread_or_keyword_arguments'
        elif len(arguments) != len(helper['parameters']):
            reason = 'argument_arity_mismatch'
        mappings = [dict(index=i,formal=p,actual=dict(code=source.text(argument),span=span(source,argument)))
                    for i,(p,argument) in enumerate(zip(helper['parameters'],arguments))] if reason is None else []
        bound = {row['formal']['name']:row for row in mappings}
        assertions = []
        if reason is None:
            for assertion in helper['assertions']:
                expected_mapping = bound.get(assertion['expected_formal'])
                assertions.append(dict(assertion, call_span=span(source,node),
                    observed_argument_bindings=[bound[name] for name in assertion['observed_formal_dependencies']],
                    expected_argument=expected_mapping['actual'] if assertion['expected_port_status']=='source_bound_candidate' and expected_mapping else None))
        row = dict(id=_id(source_sha,span(source,node)),callee=source.text(callee),span=span(source,node),
            code=source.text(node),binding_id=helper['id'] if helper else None,status='resolved' if reason is None else 'unknown',
            reason=reason,actual_formal=mappings,assertions=assertions)
        calls.append(row)
        if reason:
            unknowns.append(dict(reason=reason,call_span=row['span']))
    bindings = [dict(id=h['id'],name=h['name'],span=span(source,h['declaration']),
        function_span=span(source,h['function']),lexical_scope=span(source,h['scope']),code=source.text(h['function']),
        parameters=h['parameters'],status='resolved' if h['reason'] is None else 'unknown',reason=h['reason'],
        assertions=h['assertions']) for h in helpers]
    return dict(version=VERSION,candidate_id=candidate['id'],status='source_analysis',source_scope=dict(path=source.path,start_byte=lower,end_byte=upper),
        modified_source_sha256=source_sha,bindings=bindings,calls=calls,unknowns=unknowns,
        counts=dict(local_bindings=len(bindings),local_helper_name_calls=len(calls),resolved_calls=sum(row['status']=='resolved' for row in calls),
                    assertion_instances=sum(len(row['assertions']) for row in calls),expected_argument_ports=sum(a['expected_argument'] is not None for row in calls for a in row['assertions']),
                    unknown_reasons=dict(Counter(row['reason'] for row in calls if row['reason'])),
                    expected_port_unknown_reasons=dict(Counter(a['expected_port_reason'] for row in calls
                        for a in row['assertions'] if a['expected_port_status']=='unknown'))),
        limits=['lexical binding and per-call source arguments only','actual values and expected correctness are unknown',
                'expected argument ports are candidate syntax boundaries, not safe-edit proofs','no production oracle slots are changed'])
