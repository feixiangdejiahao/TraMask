"""Observation frontiers: a partial order on assertion value-dependence footprints.

No target labels, test names, issue text, learned weights, or model calls.
Footprint inclusion is a prioritization hypothesis, NOT logical implication of
assertions or a claim that downstream computations cannot mask faults.
"""
from __future__ import annotations

import ast
import collections
import itertools
import operator

from .syntax import ATTRS, CALLS, canonical, literal, walk


def observation_expression(assertion, source, has_origin=None):
    """Separate a simple Python comparison from its expected expression.

    Framework assertions already expose their actual argument. Compound Python
    conditions remain whole expressions; we do not invent an oracle for them.
    """
    node = assertion.expression_node
    if source.language == 'python' and node.type == 'comparison_operator' and len(node.named_children) == 2:
        left, right = node.named_children
        left_observes = has_origin(left) if has_origin else False
        right_observes = has_origin(right) if has_origin else False
        try:
            literal(source.text(left))
            left_literal = True
        except ValueError:
            left_literal = False
        if left_observes and right_observes:
            # A relation between two computed outputs must keep both sides.
            return node, ''
        if (right_observes and not left_observes) or left_literal:
            return right, source.text(left)
        return left, source.text(right)
    return node, assertion.expected


def _expected_value(node, frame):
    """Interpret only literal/parameter oracle expressions, never target calls."""
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name):
        return frame[node.id]
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        values = [_expected_value(n, frame) for n in node.elts]
        return {ast.List: list, ast.Tuple: tuple, ast.Set: set}[type(node)](values)
    if isinstance(node, ast.Dict):
        return {_expected_value(k, frame): _expected_value(v, frame) for k, v in zip(node.keys, node.values)}
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.Not, ast.USub, ast.UAdd)):
        fn = {ast.Not: operator.not_, ast.USub: operator.neg, ast.UAdd: operator.pos}[type(node.op)]
        return fn(_expected_value(node.operand, frame))
    if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub, ast.BitOr)):
        fn = {ast.Add: operator.add, ast.Sub: operator.sub, ast.BitOr: operator.or_}[type(node.op)]
        return fn(_expected_value(node.left, frame), _expected_value(node.right, frame))
    if isinstance(node, ast.Compare):
        ops = {ast.Eq: operator.eq, ast.NotEq: operator.ne, ast.Lt: operator.lt, ast.LtE: operator.le,
               ast.Gt: operator.gt, ast.GtE: operator.ge, ast.Is: operator.is_, ast.IsNot: operator.is_not,
               ast.In: lambda a, b: a in b, ast.NotIn: lambda a, b: a not in b}
        values = [_expected_value(n, frame) for n in [node.left, *node.comparators]]
        return all(ops[type(op)](a, b) for op, a, b in zip(node.ops, values, values[1:]))
    raise ValueError('unsupported oracle expression')


def expectation_diversity(expected, unit):
    if not expected or unit.source.language != 'python':
        return 1
    try:
        expr = ast.parse(expected, mode='eval').body
        groups = []
        for table in unit.parameter_rows:
            names = table['names']
            groups.append([dict(zip(names, [row] if len(names) == 1 else row)) for row in table['rows']])
        frames = (dict(pair for group in groups_row for pair in group.items())
                  for groups_row in itertools.product(*groups))
        # A finite analysis budget, not a ranking weight. Unknowns fall back to 1.
        values = set()
        for i, frame in enumerate(frames):
            if i >= 4096:
                return 1
            values.add(canonical(_expected_value(expr, frame)))
        return max(1, len(values))
    except (SyntaxError, ValueError, KeyError, TypeError, ArithmeticError):
        return 1


class ObservationFrontier:
    def __init__(self, index):
        self.index = index
        self._constant_returns = {}
        self._affected = {}

    def constant_return(self, target):
        if target not in self._constant_returns:
            unit = self.index.units[target]
            values, unknown = set(), False
            for node in walk(unit.body, stop_functions=True):
                if node.type == 'return_statement':
                    if len(node.named_children) != 1:
                        unknown = True
                        break
                    try:
                        values.add(canonical(literal(unit.source.text(node.named_children[0]))))
                    except ValueError:
                        unknown = True
                        break
            self._constant_returns[target] = next(iter(values)) if len(values) == 1 and not unknown else None
        return self._constant_returns[target]

    def value_slice(self, flow, roots):
        calls = {c.node: c for c in flow.calls}
        seen, todo, constants = set(), list(roots), set()
        while todo:
            n = todo.pop()
            if n in seen:
                continue
            seen.add(n)
            call = calls.get(n)
            if call and call.targets and all(reason not in {'unique_name_candidate', 'ambiguous_name_candidate'}
                                            for _, reason in call.targets):
                returns = {self.constant_return(uid) for uid, _ in call.targets}
                if None not in returns and len(returns) == 1:
                    constants.add(n)
                    continue
            todo.extend(d for d in flow.edges.get(n, ()) if flow.edge_kinds.get((n, d)) == 'value')
        return seen, constants

    def affected(self, uid):
        if uid not in self._affected:
            self._affected[uid] = bool(self.index.reach(uid)['changed'])
        return self._affected[uid]

    def annotate(self, flow, assertion, record):
        reachable = flow.slice([assertion.node])
        def roots(node):
            return [n for n in reachable if flow.nodes[n]['start_byte'] == node.start_byte
                    and flow.nodes[n]['end_byte'] == node.end_byte and flow.nodes[n]['kind'] != 'assertion']
        def has_origin(node):
            sliced, constants = self.value_slice(flow, roots(node))
            return any(c.node in sliced and c.node not in constants and any(self.affected(uid) for uid, _ in c.targets)
                       for c in flow.calls)
        actual, expected = observation_expression(assertion, flow.source, has_origin)
        sliced, constants = self.value_slice(flow, roots(actual) or [assertion.node])
        facts, calls = set(), []
        for call in flow.calls:
            if call.node not in sliced or call.node in constants:
                continue
            affected = []
            for uid, _ in call.targets:
                if self.affected(uid):
                    affected.append(uid)
            if affected:
                atom = f'call:{flow.unit.id}:{call.node}'
                facts.add(atom)
                calls.append({'atom': atom, 'line': flow.nodes[call.node]['line'],
                              'call': call.name, 'targets': sorted(affected)})
        observed_fields = set(flow.fields_in(actual))
        fields = []
        for witness in record['field_witnesses']:
            if witness['field'] not in observed_fields:
                continue
            for name in witness['parameters']:
                atom = f"parameter:{witness['symbol']}:{name}"
                facts.add(atom)
                fields.append({'atom': atom, 'field': witness['field'], 'writer': witness['symbol'],
                               'line': witness['line'], 'parameter': name})
        record['frontier'] = {
            'observed_expression': flow.source.text(actual), 'expected_expression': expected,
            'footprint': sorted(facts), 'calls': calls, 'field_sources': fields,
            'expected_diversity': expectation_diversity(expected, flow.unit),
            'constant_return_calls': [flow.nodes[n]['text'] for n in sorted(constants)],
        }


def order_test(rows, use_dependencies=True, use_expectation=True):
    """Peel maximal sets. Equal or incomparable observations keep a stable tie."""
    pending = list(rows)
    footprints = {r['id']: set(r['frontier']['footprint']) for r in rows}
    ordered, layer = [], 0
    while pending:
        front = [r for r in pending if not use_dependencies or not any(
            footprints[r['id']] < footprints[s['id']] or
            (footprints[r['id']] == footprints[s['id']] and r['incidental'] and not s['incidental'])
            for s in pending)]
        front.sort(key=lambda r: (-(r['frontier']['expected_diversity'] if use_expectation else 1),
                                  r['line'], r['id']))
        for row in front:
            if use_dependencies and use_expectation:
                row['frontier']['layer'] = layer
            ordered.append(row)
        removed = {r['id'] for r in front}
        pending = [r for r in pending if r['id'] not in removed]
        layer += 1
    return ordered


def rank_frontier(records, baseline_order, use_dependencies=True, use_expectation=True, test_rounds=True):
    by_test = collections.defaultdict(list)
    for row in records:
        by_test[row['test_id']].append(row)
    test_order = list(dict.fromkeys(r['test_id'] for r in baseline_order))
    queues = [collections.deque(order_test(by_test[t], use_dependencies, use_expectation)) for t in test_order]
    if not test_rounds:
        return [row for queue in queues for row in queue]
    result = []
    while queues:
        remaining = []
        for queue in queues:
            result.append(queue.popleft())
            if queue:
                remaining.append(queue)
        queues = remaining
    return result
