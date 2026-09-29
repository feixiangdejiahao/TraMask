"""Source-derived expected-argument holes for a small class of Go test helpers.

This prototype recognizes one parameter-versus-observation failure comparison,
not arbitrary assertions. It preserves prerequisite error checks and exposes
unknowns instead of guessing expected roles from names or argument positions.
No model, execution outcome, or target label is consulted.
"""
from __future__ import annotations

from collections import Counter, defaultdict

from anchor_retrieval.syntax import Source, attr_parts, call_parts, child, walk
from experimental.go_arity_guard import ArityIndex, _names


FAILURES = {'Error', 'Errorf', 'Fatal', 'Fatalf', 'Fail', 'FailNow'}
TERMINATING = {'Fatal', 'Fatalf', 'FailNow'}
# These functions return a string without mutating their string inputs. Aliases
# must resolve to these exact standard-library imports, not matching spellings.
PURE_STRING_CALLS = {'Replace', 'ReplaceAll', 'Trim', 'TrimLeft', 'TrimRight',
                     'TrimPrefix', 'TrimSuffix', 'ToLower', 'ToUpper', 'Repeat'}


def span(source, node):
    return dict(path=source.path, start_byte=node.start_byte, end_byte=node.end_byte,
                line=node.start_point.row + 1, end_line=node.end_point.row + 1)


def parameters(source, function):
    result = []
    for item in child(function, 'parameters').named_children:
        if item.type == 'comment':
            continue
        if item.type != 'parameter_declaration' or not _names(item):
            return None
        kind = source.text(child(item, 'type'))
        for name in _names(item):
            result.append(dict(name=source.text(name), type=kind))
    return result


def testing_parameters(source, params):
    aliases = {name for name, imported in source.imports.items() if imported == ('testing', None)}
    return [index for index, item in enumerate(params or [])
            if item['type'].replace(' ', '') in {f'*{alias}.T' for alias in aliases}]


def has_testing_parameter(source, function):
    """Retain unsupported variadic/unnamed helpers in the census denominator."""
    aliases = {name for name, imported in source.imports.items() if imported == ('testing', None)}
    kinds = {f'*{alias}.T' for alias in aliases}
    return any(source.text(child(item, 'type')).replace(' ', '') in kinds
               for item in child(function, 'parameters').named_children)


def statements(node):
    if node is None:
        return []
    result = []
    for item in node.named_children:
        if item.type == 'statement_list':
            result.extend(statements(item))
        elif item.type != 'comment':
            result.append(item)
    return result


def testing_call(source, node, testing_name):
    if node.type != 'call_expression':
        return None
    function, _ = call_parts(node)
    if function is None or function.type != 'selector_expression':
        return None
    owner, name = attr_parts(function)
    return source.text(name) if source.text(owner) == testing_name else None


def pure_call(source, node, shadowed):
    function, _ = call_parts(node)
    if function is None:
        return False
    if function.type == 'identifier':
        return source.text(function) in {'string', 'len', 'cap'} and source.text(function) not in shadowed
    if function.type == 'selector_expression':
        owner, name = attr_parts(function)
        return (source.text(owner) not in shadowed
                and source.imports.get(source.text(owner)) == ('strings', None)
                and source.text(name) in PURE_STRING_CALLS)
    return False


def dependencies(source, node, env):
    if node is None:
        return set()
    if node.type == 'identifier':
        return set(env.get(source.text(node), set()))
    if node.type in {'selector_expression', 'type_assertion_expression'}:
        return dependencies(source, child(node, 'operand'), env)
    if node.type == 'call_expression':
        function, arguments = call_parts(node)
        result = set().union(*(dependencies(source, item, env) for item in arguments))
        if function is not None and function.type == 'selector_expression':
            result |= dependencies(source, child(function, 'operand'), env)
        return result
    return set().union(*(dependencies(source, item, env) for item in node.named_children))


def assignments(source, node, env, definitions):
    """Conservative parameter dependencies for direct local assignments only."""
    if node.type not in {'short_var_declaration', 'assignment_statement', 'var_spec'}:
        return None
    left, right = child(node, 'left'), child(node, 'right', 'value')
    names = list(left.named_children) if left is not None else _names(node)
    if any(item.type != 'identifier' for item in names):
        return 'nonlocal_assignment'
    values = list(right.named_children) if right is not None and right.type == 'expression_list' else [right]
    if len(values) != len(names) and len(values) != 1:
        return 'unsupported_assignment_arity'
    for index, name in enumerate(names):
        label = source.text(name)
        if label == '_':
            continue
        value = values[index] if len(values) == len(names) else values[0]
        deps = dependencies(source, value, env)
        env[label] = deps
        definitions[label] = dict(name=label, span=span(source, node),
            expression=source.text(value), parameter_dependencies=sorted(deps))
    return None


def _unknown(reason, **evidence):
    return dict(status='unknown', reason=reason, **evidence)


def summarize_helper(source, function):
    params = parameters(source, function)
    tests = testing_parameters(source, params)
    identity = dict(helper=source.text(child(function, 'name')), helper_span=span(source, function))
    if params is None or len(tests) != 1:
        return _unknown('requires_one_testing_T_parameter', **identity)
    if child(function, 'result') is not None:
        return _unknown('helper_return_value_unsupported', **identity)
    testing_name = params[tests[0]]['name']
    param_names = {item['name'] for item in params}
    body = child(function, 'body')
    unsupported = {'for_statement', 'expression_switch_statement', 'type_switch_statement',
                   'select_statement', 'func_literal', 'go_statement', 'defer_statement'}
    if any(item.type in unsupported for item in walk(body)):
        return _unknown('unsupported_control_flow', **identity)
    guards, candidates, symmetric = [], [], False
    for guard in walk(body):
        if guard.type != 'if_statement':
            continue
        consequence = child(guard, 'consequence')
        failures = [item for item in walk(consequence)
                    if testing_call(source, item, testing_name) in FAILURES]
        if not failures:
            continue
        guards.append((guard, failures))
        condition = child(guard, 'condition')
        if condition is None or condition.type != 'binary_expression':
            continue
        operator = source.text(child(condition, 'operator'))
        if operator not in {'!=', '=='}:
            continue
        left, right = child(condition, 'left'), child(condition, 'right')
        bare = [item.type == 'identifier' and source.text(item) in param_names
                and source.text(item) != testing_name for item in (left, right)]
        if all(bare):
            symmetric = True
        elif any(bare):
            expected, actual = (left, right) if bare[0] else (right, left)
            candidates.append((guard, condition, expected, actual))
    if symmetric:
        return _unknown('symmetric_parameter_comparison', **identity)
    if len(candidates) != 1:
        return _unknown('requires_unique_parameter_comparison', count=len(candidates), **identity)
    guard, condition, expected, actual = candidates[0]
    expected_name = source.text(expected)
    top_level = statements(body)
    if guard not in top_level or child(guard, 'alternative') is not None:
        return _unknown('nested_or_alternative_comparison', **identity)
    env = {item['name']: {item['name']} for item in params}
    definitions, prerequisites = {}, []
    for statement in top_level:
        if statement == guard:
            break
        if statement.type == 'if_statement':
            failures = next((values for item, values in guards if item == statement), [])
            contents = statements(child(statement, 'consequence'))
            init = child(statement, 'initializer')
            if init is not None:
                error = assignments(source, init, env, definitions)
                if error:
                    return _unknown(error, **identity)
            if (not failures or child(statement, 'alternative') is not None or
                    any(testing_call(source, item, testing_name) not in TERMINATING for item in failures)
                    or len(contents) != len(failures) or
                    expected_name in dependencies(source, child(statement, 'condition'), env)):
                return _unknown('unsupported_prerequisite_guard', **identity)
            prerequisites.append(dict(span=span(source, statement),
                condition=source.text(child(statement, 'condition')),
                failure_methods=[testing_call(source, item, testing_name) for item in failures]))
        else:
            error = assignments(source, statement, env, definitions)
            if error:
                return _unknown(error, **identity)
    if expected_name in definitions:
        return _unknown('expected_reassigned_before_comparison', **identity)
    actual_deps = dependencies(source, actual, env)
    if expected_name in actual_deps:
        return _unknown('expected_also_flows_to_actual', **identity)
    data_params = actual_deps - {testing_name, expected_name}
    if not data_params:
        return _unknown('actual_not_bound_to_other_parameters', **identity)
    other_guards = [(item, failures) for item, failures in guards if item != guard]
    if len(other_guards) != len(prerequisites):
        return _unknown('additional_failure_comparison', **identity)
    contained_failures = {(item.start_byte, item.end_byte) for _, failures in guards for item in failures}
    if any(testing_call(source, item, testing_name) in FAILURES and
           (item.start_byte, item.end_byte) not in contained_failures for item in walk(body)):
        return _unknown('failure_report_outside_recognized_guards', **identity)
    # Expected taint may flow into the failure diagnostic but nowhere else. Walk
    # in source order and retain taint after a join rather than claiming precision.
    taint = {item['name']: {item['name']} for item in params}
    taint_definitions, pure_evidence = {}, []
    locals_ = param_names | {source.text(item) for node in walk(body)
        if node.type == 'short_var_declaration'
        for item in (child(node, 'left').named_children if child(node, 'left') else [])
        if item.type == 'identifier'}
    shadowed = set(locals_)
    for declaration in source.root.named_children:
        if declaration.type == 'function_declaration':
            shadowed.add(source.text(child(declaration, 'name')))
        elif declaration.type in {'var_declaration', 'const_declaration', 'type_declaration'}:
            for item in walk(declaration):
                if item.type in {'var_spec', 'const_spec', 'type_spec'}:
                    shadowed.update(source.text(name) for name in _names(item))
    for node in sorted(walk(body), key=lambda item: (item.start_byte, -item.end_byte)):
        if node.type in {'short_var_declaration', 'assignment_statement', 'var_spec'}:
            left = child(node, 'left')
            assigned = list(left.named_children) if left is not None else _names(node)
            if any(source.text(item) == testing_name for item in assigned):
                return _unknown('testing_receiver_reassigned', **identity)
            if node.type == 'assignment_statement':
                left = child(node, 'left')
                for item in left.named_children if left else []:
                    if item.type != 'identifier' or source.text(item) not in locals_:
                        return _unknown('nonlocal_assignment', **identity)
                    if source.text(item) == testing_name:
                        return _unknown('testing_receiver_reassigned', **identity)
            previous = {name: set(value) for name, value in taint.items()}
            error = assignments(source, node, taint, taint_definitions)
            if error:
                return _unknown(error, **identity)
            for name, values in previous.items():
                taint.setdefault(name, set()).update(values)
        if node.type == 'call_expression' and expected_name in dependencies(source, node, taint):
            method = testing_call(source, node, testing_name)
            in_failure = (child(guard, 'consequence').start_byte <= node.start_byte
                          and node.end_byte <= child(guard, 'consequence').end_byte)
            if method in FAILURES and in_failure:
                continue
            if pure_call(source, node, shadowed) and in_failure:
                pure_evidence.append(dict(span=span(source, node), expression=source.text(node)))
                continue
            return _unknown('expected_consumed_by_opaque_or_nondiagnostic_call',
                            consumption=span(source, node), **identity)
        if node.type == 'identifier' and source.text(node) == expected_name:
            in_comparison = condition.start_byte <= node.start_byte < condition.end_byte
            in_failure = child(guard, 'consequence').start_byte <= node.start_byte < child(guard, 'consequence').end_byte
            if not in_comparison and not in_failure:
                return _unknown('expected_used_outside_comparison_and_diagnostic', **identity)
    expected_index = next(i for i, item in enumerate(params) if item['name'] == expected_name)
    return dict(status='supported', **identity, parameters=params,
        testing_parameter_index=tests[0], expected_parameter_index=expected_index,
        comparison=dict(span=span(source, condition), operator=source.text(child(condition, 'operator')),
                        expected=source.text(expected), actual=source.text(actual)),
        actual_parameter_indices=[i for i, item in enumerate(params) if item['name'] in data_params],
        actual_parameter_dependencies=sorted(data_params),
        local_definitions=list(definitions.values()), prerequisite_guards=prerequisites,
        known_pure_diagnostic_calls=pure_evidence,
        dependency_scope='syntactic local value dependencies; no proof of callee purity for actual computation')


class HelperIndex:
    def __init__(self, corpus):
        self.corpus = corpus
        self.arity = ArityIndex(corpus)
        self.helpers, self.names = {}, set()
        for path, source in self.arity.sources.items():
            for function in source.root.named_children:
                if function.type != 'function_declaration':
                    continue
                if not has_testing_parameter(source, function):
                    continue
                key = (path, function.start_byte)
                self.helpers[key] = summarize_helper(source, function)
                self.names.add((self.arity.packages[path], source.text(child(function, 'name'))))

    def call(self, source, node):
        function, arguments = call_parts(node)
        identity = dict(call_span=span(source, node), call=source.text(node))
        if function is None or function.type != 'identifier':
            return _unknown('not_direct_same_package_call', **identity)
        signature, resolution = self.arity.resolve(source, node)
        if signature is None:
            return _unknown(resolution, **identity)
        helper = self.helpers.get((signature.path, signature.start))
        if helper is None:
            return _unknown('not_resolved_testing_helper', **identity)
        if helper['status'] != 'supported':
            return _unknown(helper['reason'], helper=helper, **identity)
        if len(arguments) != len(helper['parameters']) or any(item.type == 'variadic_argument' for item in arguments):
            return _unknown('call_argument_arity_unknown', **identity)
        expected_index = helper['expected_parameter_index']
        expected = arguments[expected_index]
        return dict(status='supported', **identity, helper=helper,
            expected_argument_index=expected_index, expected_argument=source.text(expected),
            expected_argument_span=span(source, expected),
            unchanged_callee=dict(text=source.text(function), span=span(source, function)),
            unchanged_arguments=[dict(index=i, text=source.text(item), span=span(source, item))
                                 for i, item in enumerate(arguments) if i != expected_index])

    def census(self):
        by_path = defaultdict(list)
        for test_id, test in self.corpus.get('tests', {}).items():
            if test.get('owner_kind') not in {None, 'registered_test'}:
                continue
            extent = test.get('body_span', test.get('span', {}))
            by_path[extent.get('path')].append((test_id, extent))
        counts, records = Counter(), []
        for path, owners in by_path.items():
            source = self.arity.sources.get(path)
            if source is None:
                counts['test_source_unavailable'] += len(owners)
                continue
            for node in walk(source.root):
                if node.type != 'call_expression':
                    continue
                owner_ids = [test_id for test_id, extent in owners
                    if extent.get('start_byte', -1) <= node.start_byte
                    and node.end_byte <= extent.get('end_byte', -1)]
                if not owner_ids:
                    continue
                counts['registered_test_calls'] += 1
                function, _ = call_parts(node)
                if function is None or function.type != 'identifier':
                    continue
                counts['direct_bare_calls'] += 1
                if (self.arity.packages[path], source.text(function)) not in self.names:
                    continue
                counts['same_package_testing_helper_name_calls'] += 1
                row = self.call(source, node)
                row['test_ids'] = owner_ids
                records.append(row)
                counts[row['status']] += 1
        return dict(counts=dict(counts), unknown_reasons=dict(Counter(
            row['reason'] for row in records if row['status'] == 'unknown')),
            helper_definitions=list(self.helpers.values()), records=records)
