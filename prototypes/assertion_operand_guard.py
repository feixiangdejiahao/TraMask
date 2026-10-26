"""A bounded structural guard for local oracle revisions, not an oracle proof.

Supported forms are Python single comparisons, TS expect(...).toBe/toEqual/
toStrictEqual (optionally .not), Go comparison guards, and require/assert.Equal
or NotEqual calls, and standard require/assert unary predicate pairs. Unsupported
forms return False. TS matchers and Go equality APIs are frozen; a Go unary
predicate may change only within its complementary pair. Python may change a comparison within its existing family;
equality and identity belong to one family so a None check can become a value
check. A new identity check cannot use a non-singleton literal as its expected
object. These syntax rules do not establish the intended comparison semantics.

The observed expression stays at exactly the same operand/argument position and
has the same syntactic occurrence count. Messages, Go failure bodies, and all
other assertion syntax are frozen. New expected expressions are closed literals
and containers; an existing expected expression can instead remain unchanged.
Go also permits changing the literal inside an *existing* scalar-conversion
shaped expression, such as int64(103) -> int64(5004). Without name resolution,
this cannot prove that a shadowed conversion name denotes a builtin type.

These are structural guarantees. An unchanged observer may itself have effects;
Python comparison changes may dispatch different special methods. Literal
expectations can be wrong or weaker (e.g. x == 3 -> x != None), so acceptance
never means semantic correctness or preservation of assertion strength.
"""
from __future__ import annotations

import ast

from anchor_retrieval.syntax import Source, child, walk


_PY_COMPARISONS = ({ast.Eq, ast.NotEq, ast.Is, ast.IsNot},
                   {ast.Lt, ast.LtE, ast.Gt, ast.GtE}, {ast.In, ast.NotIn})
_TS_MATCHERS = {"toBe", "toEqual", "toStrictEqual"}
_GO_COMPARISONS = {"==", "!=", "<", "<=", ">", ">="}
_GO_PREDICATE_PAIRS = (("NoError", "Error"), ("Nil", "NotNil"),
                       ("Empty", "NotEmpty"), ("True", "False"))
_GO_SCALAR_TYPES = {"int", "int8", "int16", "int32", "int64", "uint", "uint8",
                    "uint16", "uint32", "uint64", "uintptr", "float32", "float64",
                    "complex64", "complex128", "byte", "rune", "string"}


def _py_shape(node):
    return ast.dump(node, include_attributes=False) if node is not None else None


def _py_assert(source):
    body = ast.parse(source).body
    if len(body) != 1 or not isinstance(body[0], ast.Assert):
        raise ValueError("not a single assert")
    node = body[0]
    if not isinstance(node.test, ast.Compare) or len(node.test.ops) != 1:
        raise ValueError("only a single comparison is supported")
    return node


def _closed_python(node):
    # literal_eval accepts set(), but that syntax can call a shadowed function.
    if any(isinstance(part, ast.Call) for part in ast.walk(node)):
        raise ValueError("literal syntax must not add or remove a call")
    ast.literal_eval(node)


def _python(code, old, observed):
    before, after = _py_assert(old), _py_assert(code)
    target = _py_shape(ast.parse(observed, mode="eval").body)
    old_operands = [before.test.left, before.test.comparators[0]]
    new_operands = [after.test.left, after.test.comparators[0]]
    positions = [i for i, node in enumerate(old_operands) if _py_shape(node) == target]
    if len(positions) != 1:
        return False
    actual = positions[0]
    if _py_shape(new_operands[actual]) != target or _py_shape(new_operands[1-actual]) == target:
        return False
    if _py_shape(before.msg) != _py_shape(after.msg):
        return False
    if not any(type(before.test.ops[0]) in family and type(after.test.ops[0]) in family
               for family in _PY_COMPARISONS):
        return False
    if sum(_py_shape(node) == target for node in ast.walk(before)) != sum(
            _py_shape(node) == target for node in ast.walk(after)):
        return False
    expected, previous = new_operands[1-actual], old_operands[1-actual]
    if (isinstance(after.test.ops[0], (ast.Is, ast.IsNot))
            and (not isinstance(before.test.ops[0], (ast.Is, ast.IsNot))
                 or _py_shape(expected) != _py_shape(previous))):
        singleton = isinstance(expected, ast.Constant) and (expected.value is None or type(expected.value) is bool)
        existing_reference = (_py_shape(expected) == _py_shape(previous)
                              and isinstance(expected, (ast.Name, ast.Attribute, ast.Subscript, ast.Call)))
        if not singleton and not existing_reference:
            return False
    if _py_shape(expected) == _py_shape(previous):
        return True
    # Replacing an existing call/getter would remove an operation as well.
    # A bare variable may be replaced, but effectful/unknown expressions freeze.
    if not isinstance(previous, ast.Name):
        _closed_python(previous)
    _closed_python(expected)  # No calls, attribute reads, names, or short circuiting.
    return True


def _nodes(node):
    return [part for part in node.named_children if part.type != "comment"]


def _shape(source, node, hole=None):
    """Structural syntax, preserving literal contents and ignoring comments."""
    if node is None:
        return None
    if hole is not None and node.id == hole.id:
        return ("EXPECTED_HOLE",)
    if node.type == "comment":
        return None
    if not node.children:
        return node.type, source.text(node)
    return node.type, tuple(value for part in node.children
                           if (value := _shape(source, part, hole)) is not None)


def _single(source):
    if source.root.has_error:
        raise ValueError("syntax error")
    if source.language == "typescript":
        nodes = _nodes(source.root)
    else:
        functions = [node for node in source.root.named_children if node.type == "function_declaration"]
        if len(source.root.named_children) != 2 or len(functions) != 1:
            raise ValueError("invalid Go wrapper")
        body = child(functions[0], "body")
        blocks = _nodes(body)
        nodes = _nodes(blocks[0]) if len(blocks) == 1 and blocks[0].type == "statement_list" else blocks
    if len(nodes) != 1:
        raise ValueError("not a single statement")
    return nodes[0]


def _expression(text, language):
    if language == "typescript":
        source = Source("operand.ts", text, language)
        statement = _single(source)
        if statement.type != "expression_statement" or len(_nodes(statement)) != 1:
            raise ValueError("not one expression")
        return _shape(source, _nodes(statement)[0])
    source = Source("operand.go", "package guard\nvar _ = " + text, language)
    if source.root.has_error or len(source.root.named_children) != 2:
        raise ValueError("not one Go expression")
    declaration = source.root.named_children[1]
    if declaration.type != "var_declaration" or len(_nodes(declaration)) != 1:
        raise ValueError("not one Go expression")
    values = child(_nodes(declaration)[0], "value")
    if values is None or len(_nodes(values)) != 1:
        raise ValueError("not one Go expression")
    return _shape(source, _nodes(values)[0])


def _call(node):
    if node is None or node.type != "call_expression":
        raise ValueError("not a call")
    arguments = child(node, "arguments")
    if arguments is None:
        raise ValueError("missing arguments")
    return child(node, "function"), _nodes(arguments)


def _ts_parts(source):
    statement = _single(source)
    if statement.type != "expression_statement" or len(_nodes(statement)) != 1:
        raise ValueError("not one assertion call")
    matcher, arguments = _call(_nodes(statement)[0])
    if matcher.type != "member_expression" or len(arguments) != 1:
        raise ValueError("unsupported matcher")
    if source.text(child(matcher, "property")) not in _TS_MATCHERS:
        raise ValueError("unsupported matcher")
    receiver = child(matcher, "object")
    if receiver.type == "member_expression" and source.text(child(receiver, "property")) == "not":
        receiver = child(receiver, "object")
    expect, actual = _call(receiver)
    if expect.type != "identifier" or source.text(expect) != "expect" or len(actual) not in (1, 2):
        raise ValueError("unsupported expect call")
    return statement, actual[0], arguments[0]


def _closed_ts(source, node):
    if node.type in {"number", "true", "false", "null", "string"}:
        return True
    if node.type == "unary_expression":
        argument = child(node, "argument")
        return (argument is not None and argument.type == "number"
                and source.data[node.start_byte:argument.start_byte].decode().strip() in {"+", "-"})
    if node.type == "array":
        return all(_closed_ts(source, part) for part in _nodes(node))
    if node.type == "object":
        for part in _nodes(node):
            if part.type != "pair":
                return False
            key, value = child(part, "key"), child(part, "value")
            if key is None or key.type not in {"property_identifier", "string", "number"} or value is None:
                return False
            if not _closed_ts(source, value):
                return False
        return True
    return False


def _go_parts(source):
    statement = _single(source)
    if statement.type == "if_statement":
        condition = child(statement, "condition")
        if (condition is None or condition.type != "binary_expression"
                or child(statement, "initializer") is not None or child(statement, "alternative") is not None):
            raise ValueError("unsupported condition")
        left, right = child(condition, "left"), child(condition, "right")
        if left is None or right is None:
            raise ValueError("missing operands")
        operator = source.data[left.end_byte:right.start_byte].decode().strip()
        if operator not in _GO_COMPARISONS:
            raise ValueError("not a comparison")
        return statement, (left, right), None
    if statement.type != "expression_statement" or len(_nodes(statement)) != 1:
        raise ValueError("unsupported assertion")
    function, arguments = _call(_nodes(statement)[0])
    if (function.type != "selector_expression"
            or source.text(child(function, "operand")) not in {"require", "assert"}
            or source.text(child(function, "field")) not in {"Equal", "NotEqual"}
            or len(arguments) < 3):
        raise ValueError("unsupported assertion API")
    return statement, (arguments[2],), arguments[1]


def _go_predicate(source):
    """A standard unary assertion; the predicate name is the only editable part.

    This is syntax admission, not library name resolution or a semantic proof.
    Keep receiver, t, observed argument and every diagnostic argument unchanged.
    """
    statement = _single(source)
    if statement.type != "expression_statement" or len(_nodes(statement)) != 1:
        return None
    function, arguments = _call(_nodes(statement)[0])
    if (function.type != "selector_expression"
            or source.text(child(function, "operand")) not in {"require", "assert"}
            or len(arguments) < 2):
        return None
    field = child(function, "field")
    name = source.text(field)
    pair = next((pair for pair in _GO_PREDICATE_PAIRS if name in pair), None)
    return (statement, field, arguments[1], pair) if pair else None


def _closed_go(source, node):
    if node.type in {"int_literal", "float_literal", "imaginary_literal", "rune_literal",
                     "interpreted_string_literal", "raw_string_literal", "true", "false", "nil"}:
        return True
    if node.type == "unary_expression":
        operand = child(node, "operand")
        return (operand is not None and operand.type in {"int_literal", "float_literal", "imaginary_literal"}
                and source.data[node.start_byte:operand.start_byte].decode().strip() in {"+", "-"})
    return False


def _existing_go_conversion(before, old, after, new):
    if old.type != "call_expression" or new.type != "call_expression":
        return False
    left, old_args = _call(old)
    right, new_args = _call(new)
    return (left.type == right.type == "identifier" and before.text(left) in _GO_SCALAR_TYPES
            and _shape(before, left) == _shape(after, right) and len(old_args) == len(new_args) == 1
            and _closed_go(before, old_args[0]) and _closed_go(after, new_args[0]))


def _trees(code, old, observed, language):
    wrap = (lambda text: text) if language == "typescript" else (lambda text: "package guard\nfunc check(){\n" + text + "\n}")
    before, after = (Source("assertion", wrap(text), language) for text in (old, code))
    target = _expression(observed, language)
    if language == "go":
        old_predicate, new_predicate = _go_predicate(before), _go_predicate(after)
        if old_predicate is not None or new_predicate is not None:
            if old_predicate is None or new_predicate is None:
                return False
            old_node, old_method, old_actual, old_pair = old_predicate
            new_node, new_method, new_actual, new_pair = new_predicate
            return (old_pair == new_pair
                    and _shape(before, old_actual) == _shape(after, new_actual) == target
                    and _shape(before, old_node, old_method) == _shape(after, new_node, new_method))
    if language == "typescript":
        old_node, old_actual, old_expected = _ts_parts(before)
        new_node, new_actual, new_expected = _ts_parts(after)
    else:
        old_node, old_operands, old_expected = _go_parts(before)
        new_node, new_operands, new_expected = _go_parts(after)
        positions = [i for i, node in enumerate(old_operands) if _shape(before, node) == target]
        if len(positions) != 1 or len(old_operands) != len(new_operands):
            return False
        position = positions[0]
        old_actual, new_actual = old_operands[position], new_operands[position]
        if old_expected is None:
            old_expected, new_expected = old_operands[1-position], new_operands[1-position]
    if _shape(before, old_actual) != target or _shape(after, new_actual) != target:
        return False
    if _shape(before, old_expected) == target or _shape(after, new_expected) == target:
        return False
    # Only the expected subtree is editable. This also freezes evaluation order,
    # matcher/negation/message and Go failure-body syntax, rather than just text.
    if _shape(before, old_node, old_expected) != _shape(after, new_node, new_expected):
        return False
    if sum(_shape(before, node) == target for node in walk(old_node)) != sum(
            _shape(after, node) == target for node in walk(new_node)):
        return False
    if _shape(before, old_expected) == _shape(after, new_expected):
        return True
    if language == "typescript":
        return ((old_expected.type == "identifier" or _closed_ts(before, old_expected))
                and _closed_ts(after, new_expected))
    return ((old_expected.type == "identifier" or _closed_go(before, old_expected))
            and _closed_go(after, new_expected)) or _existing_go_conversion(before, old_expected, after, new_expected)


def valid_assertion(code, old, observed, language):
    """Accept only a supported structural revision; no semantic validity claim."""
    try:
        if language not in {"python", "typescript", "go"} or not all(
                isinstance(value, str) and 0 < len(value.encode()) <= 20000 for value in (code, old, observed)):
            return False
        return _python(code, old, observed) if language == "python" else _trees(code, old, observed, language)
    except (ValueError, SyntaxError, TypeError, AttributeError, KeyError, IndexError, RecursionError, OverflowError, UnicodeError):
        return False
