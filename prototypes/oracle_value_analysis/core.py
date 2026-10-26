"""Linear observed-value substitution with a small, non-executing interpreter.

Source equalities are supplied observations, not facts verified by this module.
A conditional result additionally requires the carrier's equality to support
substitution into the accepted builtin-value context. Python overloaded __eq__
and operators do not in general satisfy this premise.
"""
from __future__ import annotations

import ast
import copy
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Equation:
    actual: str
    expected: str


@dataclass(frozen=True)
class Derivation:
    status: str
    actual: str | None = None
    expected: str | None = None
    context: str | None = None
    checks: dict = field(default_factory=dict)
    reason: str | None = None
    premises: tuple[str, ...] = ()


class _Hole(ast.expr):
    _fields = ()


class _Unsupported(ValueError):
    pass


def _same(left, right):
    return ast.dump(left, include_attributes=False) == ast.dump(right, include_attributes=False)


def _fill(context, expression):
    class Fill(ast.NodeTransformer):
        def visit__Hole(self, node):
            return copy.deepcopy(expression)
    return ast.fix_missing_locations(Fill().visit(copy.deepcopy(context)))


def _equal(left, right):
    # Python's True == 1 is not enough to identify an observed value/type.
    return type(left) is type(right) and (all(_equal(a, b) for a, b in zip(left, right))
        and len(left) == len(right) if type(left) in (list, tuple) else left == right)


class _Constants:
    def __init__(self, max_items):
        self.max_items = max_items

    def bounded(self, value):
        remaining = self.max_items

        def inspect(item):
            nonlocal remaining
            remaining -= 1
            if remaining < 0:
                raise _Unsupported('constant_value_budget')
            if type(item) in (list, tuple):
                if len(item) > self.max_items:
                    raise _Unsupported('constant_value_budget')
                for element in item:
                    inspect(element)
            elif type(item) is str:
                remaining -= len(item)
                if remaining < 0:
                    raise _Unsupported('constant_value_budget')
            elif type(item) is int and item.bit_length() > 4096:
                raise _Unsupported('integer_bit_budget')
        inspect(value)
        return value

    def evaluate(self, node, carrier=None):
        if isinstance(node, _Hole):
            return self.bounded(carrier)
        if isinstance(node, ast.Constant):
            if type(node.value) not in (type(None), bool, int, str):
                raise _Unsupported('unsupported_constant_type')
            return self.bounded(node.value)
        if isinstance(node, (ast.List, ast.Tuple)):
            values = [self.evaluate(element, carrier) for element in node.elts]
            return self.bounded(values if isinstance(node, ast.List) else tuple(values))
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            value = self.evaluate(node.operand, carrier)
            if type(value) is not int:
                raise _Unsupported('unsupported_operator_types')
            return self.bounded(value if isinstance(node.op, ast.UAdd) else -value)
        if isinstance(node, ast.BinOp):
            left, right = self.evaluate(node.left, carrier), self.evaluate(node.right, carrier)
            integers = type(left) is int and type(right) is int
            if isinstance(node.op, ast.Add) and type(left) is type(right) and type(left) in (int, str, list, tuple):
                if type(left) in (str, list, tuple) and len(left) + len(right) > self.max_items:
                    raise _Unsupported('constant_value_budget')
                value = left + right
            elif integers and isinstance(node.op, ast.Sub):
                value = left - right
            elif isinstance(node.op, ast.Mult):
                if integers:
                    value = left * right
                else:
                    sequence, count = (left, right) if type(right) is int else (right, left)
                    if type(sequence) not in (str, list, tuple) or type(count) is not int:
                        raise _Unsupported('unsupported_operator_types')
                    if len(sequence) * max(0, count) > self.max_items:
                        raise _Unsupported('constant_value_budget')
                    try:
                        value = sequence * count
                    except OverflowError:
                        raise _Unsupported('undefined_constant_operation') from None
            elif integers and isinstance(node.op, (ast.FloorDiv, ast.Mod)):
                if right == 0:
                    raise _Unsupported('undefined_constant_operation')
                value = left // right if isinstance(node.op, ast.FloorDiv) else left % right
            else:
                raise _Unsupported('unsupported_operator_or_types')
            return self.bounded(value)
        # No Call, Attribute, Name, indexing, comparisons, comprehension, boolean
        # short circuit, mutable update, or subject-defined operator is executed.
        raise _Unsupported('unsupported_context_node:' + type(node).__name__)


def derive(A: Equation, B: Equation, C: Equation, *, max_nodes=256, max_items=1024) -> Derivation:
    """Find K[A.actual]=B.actual, check K[A.expected]=B.expected, then substitute.

    The carrier must occur exactly once as a complete AST expression. Matching
    never replaces another literal because it equals A.expected. Ground values
    are interpreted by the whitelist above, never by eval or subject execution.
    ``conditional`` describes a symbolic derivation under the reported premises;
    it is not a proof that the source observations imply Python substitutivity.
    """
    if type(max_nodes) is not int or max_nodes < 1 or type(max_items) is not int or max_items < 1:
        raise ValueError('budgets must be positive integers')
    checks = {}
    try:
        def parse(text):
            try:
                node = ast.parse(text, mode='eval').body
            except SyntaxError:
                raise _Unsupported('expression_syntax') from None
            if sum(1 for _ in ast.walk(node)) > max_nodes:
                raise _Unsupported('expression_node_budget')
            return node

        a, b, c = (parse(e.actual) for e in (A, B, C))
        count = 0

        class Abstract(ast.NodeTransformer):
            def visit(self, node):
                nonlocal count
                if isinstance(node, ast.expr) and _same(node, a):
                    count += 1
                    return _Hole()
                return super().visit(node)

        context = Abstract().visit(copy.deepcopy(b))
        if count != 1:
            raise _Unsupported('carrier_not_unique' if count > 1 else 'carrier_missing')
        if isinstance(context, _Hole):
            raise _Unsupported('identity_context')
        checks['carrier_occurs_once'] = True
        checks['B_actual_reconstructed'] = _same(_fill(context, a), b)
        if not checks['B_actual_reconstructed']:
            raise _Unsupported('source_actual_not_reconstructed')
        constants = _Constants(max_items)
        av, bv, cv = (constants.evaluate(parse(e.expected)) for e in (A, B, C))
        checks['B_expected_recomputed'] = _equal(constants.evaluate(context, av), bv)
        if not checks['B_expected_recomputed']:
            raise _Unsupported('source_expected_not_explained')
        expected = constants.evaluate(context, cv)
        generated = _fill(context, c)
        actual_text, expected_text = ast.unparse(generated), repr(expected)
        checks['D_expected_roundtrips'] = _equal(constants.evaluate(parse(expected_text)), expected)
        return Derivation('conditional', actual_text, expected_text,
                          ast.unparse(_fill(context, ast.Name(id='observed_value', ctx=ast.Load()))),
                          checks, premises=('source_observation_equalities_hold',
                                            'carrier_has_builtin_value_semantics',
                                            'matched_carrier_binding_and_evaluation_context_preserved'))
    except _Unsupported as exc:
        return Derivation('unsupported', checks=checks, reason=str(exc))
