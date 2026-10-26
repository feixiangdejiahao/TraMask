"""Small, source-anchored observation transformers; never execute a SUT oracle.

``validate_completions(payload, candidates)`` is the model boundary. Candidates
contain ``candidate_id``, ``language``, ``pre``, ``arg``, and ``observations``.
Only the first two value lists enter the expression interpreter. Observations
are numbered, program-owned records; their code is never interpreted here.

An optional witness is ``{pre, arg, after, observe}``. Witnesses can refute a
relation, never prove it. Source values must be known: use ``unknown(reason)``
or the JSON value ``{"$unknown": reason}`` for unsupported source expressions.
JSON tags preserve tuple, set, bytes, and non-string-keyed maps. No actual-value
slot exists, and source expressions containing calls are not evaluated.
"""
from __future__ import annotations

import ast
from dataclasses import dataclass
import json
import math
import operator
import re
import struct
from typing import Any


class OracleError(ValueError):
    def __init__(self, code: str, reason: str):
        self.code, self.reason = code, reason
        super().__init__(reason)


@dataclass(frozen=True)
class Unknown:
    reason: str = "Source expected value is not statically known"


def unknown(reason: str = "Source expected value is not statically known") -> Unknown:
    return Unknown(reason)


@dataclass(frozen=True)
class Limits:
    expression_bytes: int = 4096
    expression_nodes: int = 256
    depth: int = 32
    value_nodes: int = 16384
    container_items: int = 4096
    text_bytes: int = 65536
    integer_bits: int = 4096
    payload_bytes: int = 1_048_576
    completions: int = 256


DEFAULT_LIMITS = Limits()


def _fail(code: str, reason: str):
    raise OracleError(code, reason)


def _copy_value(value: Any, limits: Limits = DEFAULT_LIMITS, *, allow_unknown=False) -> Any:
    """Validate and copy exact builtin values, without invoking user methods."""
    count, text_size = 0, 0
    active: set[int] = set()

    def visit(v, depth):
        nonlocal count, text_size
        count += 1
        if count > limits.value_nodes or depth > limits.depth:
            _fail("value_budget", "Source or result value exceeds the structural budget")
        typ = type(v)
        if typ is Unknown:
            if allow_unknown and type(v.reason) is str:
                visit(v.reason, depth + 1)
                return v
            _fail("unsupported_source_value", v.reason)
        if v is None or typ is bool:
            return v
        if typ is int:
            if v.bit_length() > limits.integer_bits:
                _fail("value_budget", "Integer exceeds the bit budget")
            return v
        if typ is float:
            if not math.isfinite(v):
                _fail("unsupported_value", "Non-finite floating-point values are unsupported")
            return v
        if typ in {str, bytes}:
            text_size += len(v.encode("utf-8", "surrogatepass")) if typ is str else len(v)
            if text_size > limits.text_bytes:
                _fail("value_budget", "Text exceeds the byte budget")
            return v
        if typ not in {list, tuple, set, frozenset, dict}:
            _fail("unsupported_value", f"Unsupported value type: {typ.__name__}")
        if len(v) > limits.container_items or id(v) in active:
            _fail("value_budget", "Container is cyclic or exceeds the item budget")
        active.add(id(v))
        try:
            if typ is dict:
                return {visit(k, depth + 1): visit(x, depth + 1) for k, x in v.items()}
            values = [visit(x, depth + 1) for x in v]
            return typ(values)
        finally:
            active.remove(id(v))

    return visit(value, 0)


_TAGS = {"$tuple", "$set", "$frozenset", "$bytes_hex", "$mapping", "$unknown"}


def _stable_value_key(value):
    """A type-sensitive structural order, independent of hash iteration order."""
    typ = type(value)
    if typ in {list, tuple}:
        return (typ.__name__, tuple(_stable_value_key(v) for v in value))
    if typ in {set, frozenset}:
        return (typ.__name__, tuple(sorted(_stable_value_key(v) for v in value)))
    if typ is dict:
        # Insertion order is observable for dictionaries; do not sort their items.
        return ('dict', tuple((_stable_value_key(k), _stable_value_key(v)) for k, v in value.items()))
    return (typ.__name__, repr(value))


def _python_literal(value):
    """Canonical closed expressions; preserve ordered containers and exact types."""
    typ = type(value)
    if typ is list:
        return '[' + ', '.join(_python_literal(v) for v in value) + ']'
    if typ is tuple:
        items = ', '.join(_python_literal(v) for v in value)
        return '(' + items + (',' if len(value) == 1 else '') + ')'
    if typ is dict:
        return '{' + ', '.join(_python_literal(k) + ': ' + _python_literal(v)
                               for k, v in value.items()) + '}'
    if typ in {set, frozenset}:
        if not value:
            return 'set()' if typ is set else 'frozenset()'
        items = '{' + ', '.join(_python_literal(v) for v in sorted(value, key=_stable_value_key)) + '}'
        return items if typ is set else 'frozenset(' + items + ')'
    return repr(value)


def _contains_unordered(value):
    """Whether a builtin str conversion would expose set iteration order."""
    typ = type(value)
    if typ in {set, frozenset}:
        return True
    if typ in {list, tuple}:
        return any(_contains_unordered(v) for v in value)
    if typ is dict:
        return any(_contains_unordered(k) or _contains_unordered(v) for k, v in value.items())
    return False


def encode_value(value: Any, *, limits: Limits = DEFAULT_LIMITS) -> Any:
    """JSON-safe values preserving mapping order even with JSON key sorting."""
    if type(value) is Unknown:
        return {"$unknown": value.reason}
    value = _copy_value(value, limits, allow_unknown=True)

    def enc(v):
        typ = type(v)
        if typ is Unknown:
            return {"$unknown": v.reason}
        if typ is tuple:
            return {"$tuple": [enc(x) for x in v]}
        if typ in {set, frozenset}:
            return {"$set" if typ is set else "$frozenset": [enc(x) for x in sorted(v, key=_stable_value_key)]}
        if typ is bytes:
            return {"$bytes_hex": v.hex()}
        if typ is list:
            return [enc(x) for x in v]
        if typ is dict:
            # Model/cache JSON is canonically key-sorted. A pair array retains
            # the source order, which list(dict) and str(dict) can observe.
            return {"$mapping": [[enc(k), enc(x)] for k, x in v.items()]}
        return v

    return enc(value)


def decode_value(value: Any, *, limits: Limits = DEFAULT_LIMITS) -> Any:
    """Decode the small JSON tag vocabulary; reject malformed or oversized tags."""
    # Check size before interpreting tags, which could otherwise allocate freely.
    if type(value) is Unknown:
        return value
    value = _copy_value(value, limits)

    def dec(v):
        if type(v) in {list, tuple, set, frozenset}:
            return type(v)(dec(x) for x in v)
        if type(v) is not dict:
            return v
        if len(v) == 1 and next(iter(v)) in _TAGS:
            tag, content = next(iter(v.items()))
            if tag == "$unknown":
                if type(content) is not str:
                    _fail("invalid_tag", "$unknown requires a string reason")
                return Unknown(content)
            if tag == "$bytes_hex":
                if type(content) is not str or not re.fullmatch(r"(?:[0-9a-fA-F]{2})*", content):
                    _fail("invalid_tag", "$bytes_hex requires an even-length hexadecimal string")
                return bytes.fromhex(content)
            if type(content) is not list:
                _fail("invalid_tag", f"{tag} requires an array")
            if tag == "$mapping":
                out = {}
                for pair in content:
                    if type(pair) is not list or len(pair) != 2:
                        _fail("invalid_tag", "$mapping entries must be key/value pairs")
                    key, item = map(dec, pair)
                    try:
                        if key in out:
                            _fail("duplicate_value", "Duplicate key in tagged mapping")
                        out[key] = item
                    except TypeError:
                        _fail("invalid_tag", "Unhashable tagged mapping key")
                return out
            values = [dec(x) for x in content]
            constructor = {"$tuple": tuple, "$set": set, "$frozenset": frozenset}[tag]
            try:
                result = constructor(values)
            except TypeError:
                _fail("invalid_tag", "Set entries must be hashable")
            if constructor is not tuple and len(result) != len(values):
                _fail("duplicate_value", "Duplicate entry in tagged set")
            return result
        return {dec(k): dec(x) for k, x in v.items()}

    return dec(value)


def _tree(expression: str, limits: Limits) -> ast.Expression:
    if type(expression) is not str or not expression.strip():
        _fail("invalid_expression", "Expression must be a nonempty string")
    if len(expression.encode("utf-8", "surrogatepass")) > limits.expression_bytes:
        _fail("expression_budget", "Expression exceeds the byte budget")
    try:
        tree = ast.parse(expression, mode="eval")
    except (SyntaxError, ValueError, RecursionError, MemoryError) as exc:
        _fail("invalid_expression", f"Cannot parse expression: {type(exc).__name__}")
    pending, count = [(tree, 0)], 0
    while pending:
        node, depth = pending.pop()
        count += 1
        if count > limits.expression_nodes or depth > limits.depth:
            _fail("expression_budget", "Expression exceeds the AST budget")
        pending.extend((c, depth + 1) for c in ast.iter_child_nodes(node))
    return tree


_BINARY = {
    ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
    ast.Div: operator.truediv, ast.FloorDiv: operator.floordiv, ast.Mod: operator.mod,
    ast.BitOr: operator.or_, ast.BitAnd: operator.and_, ast.BitXor: operator.xor,
}
_COMPARE = {
    ast.Eq: operator.eq, ast.NotEq: operator.ne, ast.Lt: operator.lt,
    ast.LtE: operator.le, ast.Gt: operator.gt, ast.GtE: operator.ge,
    ast.In: lambda a, b: a in b, ast.NotIn: lambda a, b: a not in b,
}
_BUILTINS = {"len": len, "str": str, "tuple": tuple, "list": list, "set": set}


def _validate_tree(tree: ast.Expression):
    allowed = (ast.Expression, ast.Constant, ast.Name, ast.Load, ast.List, ast.Tuple,
               ast.Set, ast.Dict, ast.Subscript, ast.Slice, ast.BinOp, ast.UnaryOp,
               ast.BoolOp, ast.Compare, ast.IfExp, ast.Call,
               *tuple(_BINARY), *tuple(_COMPARE), ast.UAdd, ast.USub, ast.Not,
               ast.And, ast.Or)
    for node in ast.walk(tree):
        if not isinstance(node, allowed):
            _fail("impure_expression", f"Unsupported expression node: {type(node).__name__}")
        if isinstance(node, ast.Name) and node.id not in {"pre", "arg", *_BUILTINS}:
            _fail("impure_expression", f"Unknown name: {node.id}")
        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name) or node.func.id not in _BUILTINS:
                _fail("impure_expression", "Only named, explicitly allowed pure builtins may be called")
            if node.keywords or len(node.args) != 1:
                _fail("invalid_expression", "Pure builtin calls require exactly one positional argument")
        if isinstance(node, ast.Dict) and any(key is None for key in node.keys):
            _fail("impure_expression", "Dictionary unpacking is unsupported")


def evaluate_expression(expression: str, pre=(), arg=(), *, limits: Limits = DEFAULT_LIMITS) -> Any:
    """Interpret a pure Python-expression DSL on copied, frozen source values.

    There is no eval/exec, attribute access, arbitrary call, comprehension, or
    actual/SUT binding. Both branches are syntax-validated before evaluation.
    """
    tree = _tree(expression, limits)
    _validate_tree(tree)
    if type(pre) not in {tuple, list} or type(arg) not in {tuple, list}:
        _fail("candidate_schema", "Source slot lists must be exact builtin sequences")
    values = {"pre": _copy_value(list(pre), limits), "arg": _copy_value(list(arg), limits)}

    def checked(value):
        return _copy_value(value, limits)

    def run(node):
        if isinstance(node, ast.Constant):
            return checked(node.value)
        if isinstance(node, ast.Name):
            if node.id in values:
                return values[node.id]
            _fail("invalid_expression", "Builtin names may only occur as call targets")
        if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
            result = [run(x) for x in node.elts]
            if isinstance(node, ast.List):
                return checked(result)
            if isinstance(node, ast.Tuple):
                return checked(tuple(result))
            result_set = set(result)
            if len(result_set) != len(result):
                _fail("duplicate_value", "Duplicate entry in set expression")
            return checked(result_set)
        if isinstance(node, ast.Dict):
            result = {}
            for k, v in zip(node.keys, node.values):
                key = run(k)
                if key in result:
                    _fail("duplicate_value", "Duplicate key in dictionary expression")
                result[key] = run(v)
            return checked(result)
        if isinstance(node, ast.Subscript):
            value = run(node.value)
            if isinstance(node.slice, ast.Slice):
                parts = [run(n) if n is not None else None
                         for n in (node.slice.lower, node.slice.upper, node.slice.step)]
                if any(x is not None and type(x) is not int for x in parts):
                    _fail("index_type", "Slice boundaries must be integers")
                if parts[2] == 0:
                    _fail("index_type", "Slice step cannot be zero")
                key = slice(*parts)
            else:
                key = run(node.slice)
                if type(value) in {list, tuple, str, bytes} and type(key) is not int:
                    _fail("index_type", "Sequence indices must be integers, not booleans")
                if isinstance(node.value, ast.Name) and node.value.id in values:
                    if type(key) is not int or key < 0:
                        _fail("index_type", "Source slot indices must be nonnegative integers")
            return checked(value[key])
        if isinstance(node, ast.BinOp):
            left, right = run(node.left), run(node.right)
            if isinstance(node.op, ast.Mult):
                for seq, multiplier in ((left, right), (right, left)):
                    if type(seq) in {str, bytes, list, tuple} and type(multiplier) is int:
                        cap = limits.text_bytes if type(seq) in {str, bytes} else limits.container_items
                        if len(seq) * max(0, multiplier) > cap:
                            _fail("value_budget", "Repetition exceeds the output budget")
                if type(left) is int and type(right) is int:
                    if left.bit_length() + right.bit_length() > limits.integer_bits + 1:
                        _fail("value_budget", "Multiplication exceeds the integer budget")
            if isinstance(node.op, ast.Mod) and type(left) in {str, bytes}:
                _fail("impure_expression", "String formatting is not part of the expression DSL")
            return checked(_BINARY[type(node.op)](left, right))
        if isinstance(node, ast.UnaryOp):
            operand = run(node.operand)
            if isinstance(node.op, ast.Not):
                return not operand
            return checked(operator.pos(operand) if isinstance(node.op, ast.UAdd) else operator.neg(operand))
        if isinstance(node, ast.BoolOp):
            result = run(node.values[0])
            for value in node.values[1:]:
                if isinstance(node.op, ast.And) and not result:
                    break
                if isinstance(node.op, ast.Or) and result:
                    break
                result = run(value)
            return checked(result)
        if isinstance(node, ast.Compare):
            left = run(node.left)
            for operation, next_node in zip(node.ops, node.comparators):
                right = run(next_node)
                if not _COMPARE[type(operation)](left, right):
                    return False
                left = right
            return True
        if isinstance(node, ast.IfExp):
            return run(node.body if run(node.test) else node.orelse)
        if isinstance(node, ast.Call):
            argument = run(node.args[0])
            name = node.func.id
            if ((name in {'list', 'tuple'} and type(argument) in {set, frozenset})
                    or name == 'str' and _contains_unordered(argument)):
                _fail('unordered_conversion', 'Order-sensitive conversion of a set/frozenset is unsupported')
            return checked(_BUILTINS[name](argument))
        _fail("invalid_expression", f"Cannot evaluate node: {type(node).__name__}")

    try:
        return checked(run(tree.body))
    except OracleError:
        raise
    except (IndexError, KeyError) as exc:
        _fail("index_error", f"Expression accesses an unavailable index/key: {exc}")
    except (TypeError, ValueError, ZeroDivisionError, OverflowError) as exc:
        _fail("expression_type", f"Expression cannot operate on these source values: {exc}")


def expression_dependencies(expression: str, *, limits: Limits = DEFAULT_LIMITS) -> dict:
    tree = _tree(expression, limits)
    _validate_tree(tree)
    names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    return {"uses_pre": "pre" in names, "uses_arg": "arg" in names}


def same_value(left: Any, right: Any) -> bool:
    """Strict source-witness equality, including bool/int and list/tuple distinctions."""
    if type(left) is not type(right):
        return False
    if type(left) in {list, tuple}:
        return len(left) == len(right) and all(same_value(a, b) for a, b in zip(left, right))
    if type(left) is dict:
        return len(left) == len(right) and all(
            any(same_value(k, rk) and same_value(v, rv) for rk, rv in right.items())
            for k, v in left.items())
    if type(left) in {set, frozenset}:
        return len(left) == len(right) and all(any(same_value(a, b) for b in right) for a in left)
    return left == right


def parse_source_literal(text: str, language: str = "python", *, limits: Limits = DEFAULT_LIMITS) -> Any:
    """Read closed literal syntax only; unsupported syntax returns Unknown.

    Python literal containers and JSON-like TS literals are supported. Go
    scalar literals and typed slices/arrays/maps use a tiny literal parser.
    Calls (including SUT constructors) remain unknown.
    """
    try:
        if type(text) is not str:
            _fail("unsupported_source_value", "Source expression is not text")
        if len(text.encode("utf-8", "surrogatepass")) > limits.expression_bytes:
            _fail("expression_budget", "Source literal exceeds the byte budget")
        if language == "python":
            tree = _tree(text, limits)
            if any(isinstance(node, ast.Call) for node in ast.walk(tree)):
                _fail("unsupported_source_value", "Source calls require binding and semantic evidence")
            return _copy_value(ast.literal_eval(tree), limits)
        if language in {"typescript", "javascript", "ts", "go"}:
            return _parse_foreign_literal(text, language, limits)
        _fail("unsupported_language", f"Unsupported source language: {language}")
    except (OracleError, SyntaxError, ValueError, TypeError, RecursionError) as exc:
        return Unknown(str(exc))


def _foreign_string(raw, language):
    if not raw or raw[0] not in {'"', "'"} or raw[-1] != raw[0]:
        _fail("unsupported_source_value", "Unsupported foreign string spelling")
    quote, body, out, index = raw[0], raw[1:-1], [], 0
    simple = {"b": "\b", "f": "\f", "n": "\n", "r": "\r", "t": "\t", "v": "\v",
              "\\": "\\", '"': '"', "'": "'"}
    if language == "go":
        simple["a"] = "\a"
    else:
        simple["/"] = "/"
    while index < len(body):
        char = body[index]
        index += 1
        if char != "\\":
            if char == quote or char in "\n\r":
                _fail("unsupported_source_value", "Invalid unescaped foreign string character")
            out.append(char)
            continue
        if index == len(body):
            _fail("unsupported_source_value", "Incomplete foreign string escape")
        escape = body[index]
        index += 1
        if escape in simple:
            out.append(simple[escape])
            continue
        if escape in {"x", "u", "U"}:
            if escape == "U" and language != "go":
                # JS treats this as an identity escape, not Python's Unicode escape.
                out.append("U")
                continue
            count = {"x": 2, "u": 4, "U": 8}[escape]
            digits = body[index:index + count]
            if len(digits) != count or not re.fullmatch(r"[0-9a-fA-F]+", digits):
                _fail("unsupported_source_value", "Unsupported foreign hexadecimal escape")
            index += count
            number = int(digits, 16)
            if number > 0x10FFFF or (language == "go" and 0xD800 <= number <= 0xDFFF):
                _fail("unsupported_source_value", "Invalid Unicode codepoint")
            if language == "go" and escape == "x" and number >= 128:
                _fail("unsupported_source_value", "Non-UTF8 Go byte strings require an explicit byte representation")
            out.append(chr(number))
            continue
        if escape == "0" and language != "go" and (index == len(body) or not body[index].isdigit()):
            out.append("\0")
            continue
        if language == "go" and escape in "01234567":
            digits = escape + body[index:index + 2]
            if len(digits) != 3 or not re.fullmatch(r"[0-7]{3}", digits) or int(digits, 8) >= 128:
                _fail("unsupported_source_value", "Unsupported Go octal byte escape")
            out.append(chr(int(digits, 8)))
            index += 2
            continue
        if language != "go" and not escape.isdigit():
            if escape == "\n":
                continue
            if escape == "\r":
                if index < len(body) and body[index] == "\n":
                    index += 1
                continue
            out.append(escape)
            continue
        _fail("unsupported_source_value", "Unsupported foreign string escape")
    result = "".join(out)
    if language == "go" and quote == "'":
        if len(result) != 1:
            _fail("unsupported_source_value", "Go rune literals require exactly one character")
        return ord(result)
    if language != "go":
        # JS has UTF-16 strings. Canonicalize valid surrogate pairs while retaining lone ones.
        result = result.encode("utf-16-le", "surrogatepass").decode("utf-16-le", "surrogatepass")
    return result


def _parse_foreign_literal(text, language, limits):
    # JSON constants are rewritten as AST names, never by replacing text inside strings.
    text = text.strip()
    if language == "go" and text.startswith("`") and text.endswith("`") and "`" not in text[1:-1]:
        return _copy_value(text[1:-1].replace("\r", ""), limits)
    if language == "go":
        match = re.fullmatch(r"(\[\]\w+|\[\d+\]\w+|map\[\w+\]\w+)\s*\{(.*)\}", text, re.S)
        if match:
            hint, body = match.groups()
            body = body.rstrip().removesuffix(",")
            text = "{" + body + "}" if hint.startswith("map[") else "[" + body + "]"
    tree = _tree(text, limits)

    def parse(node):
        if isinstance(node, ast.Constant):
            raw = ast.get_source_segment(text, node)
            if type(node.value) is str:
                return _foreign_string(raw, language)
            if type(node.value) in {bool, type(None), bytes}:
                _fail("unsupported_source_value", "Python-only foreign literal spelling")
            return _copy_value(node.value, limits)
        if isinstance(node, ast.Name) and node.id in {"true", "false", "null", "nil"}:
            return {"true": True, "false": False, "null": None, "nil": None}[node.id]
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            value = parse(node.operand)
            if type(value) not in {int, float}:
                _fail("unsupported_source_value", "Unary source literal requires a number")
            return value if isinstance(node.op, ast.UAdd) else -value
        if isinstance(node, ast.List):
            return [parse(n) for n in node.elts]
        if isinstance(node, ast.Dict):
            result = {}
            for key, value in zip(node.keys, node.values):
                if key is None:
                    _fail("unsupported_source_value", "Source dictionary unpacking is unsupported")
                k = key.id if isinstance(key, ast.Name) and language != "go" else parse(key)
                if k in result:
                    _fail("duplicate_value", "Duplicate key in source literal")
                result[k] = parse(value)
            return result
        _fail("unsupported_source_value", "Source expression is not supported literal syntax")

    result = _copy_value(parse(tree.body), limits)
    # Python accepts syntax that has no matching Go/TS meaning. Keep this reader
    # deliberately narrow rather than pretending to evaluate those languages.
    if isinstance(tree.body, ast.Constant) and type(result) is bytes:
        _fail("unsupported_source_value", "Foreign byte string syntax is unsupported")
    return result


_GO_ATOMS = {"string", "bool", "int", "int8", "int16", "int32", "int64", "uint", "uint8", "uint16", "uint32", "uint64", "byte", "rune", "float32", "float64", "any", "interface{}"}


def _go_type(hint: str):
    if type(hint) is not str:
        _fail("literal_type", "Go type hint must be a string")
    hint = hint.strip()
    if hint in _GO_ATOMS:
        return ("atom", hint)
    match = re.fullmatch(r"\[(\d*)\](.+)", hint)
    if match:
        size, child = match.groups()
        if size and len(size) > 6:
            _fail("literal_type", "Go array size exceeds the budget")
        return ("sequence", int(size) if size else None, _go_type(child))
    if hint.startswith("map["):
        level = 1
        for i in range(4, len(hint)):
            if hint[i] == "[":
                level += 1
            elif hint[i] == "]":
                level -= 1
                if level == 0:
                    key, value = _go_type(hint[4:i]), _go_type(hint[i + 1:])
                    if key[0] != "atom":
                        _fail("literal_type", "Only scalar Go map keys are supported")
                    return ("map", key, value)
    _fail("literal_type", f"Unsupported Go type hint: {hint}")


def _go_infer(value):
    typ = type(value)
    if typ in {str, bool, int, float}:
        return {str: "string", bool: "bool", int: "int", float: "float64"}[typ]
    if typ is bytes:
        return "[]byte"
    if typ is list and value:
        types = {_go_infer(v) for v in value}
        if len(types) == 1:
            return "[]" + next(iter(types))
    if typ is dict and value:
        keys, vals = {_go_infer(k) for k in value}, {_go_infer(v) for v in value.values()}
        if len(keys) == len(vals) == 1:
            return "map[" + next(iter(keys)) + "]" + next(iter(vals))
    _fail("literal_type", "Go container type is ambiguous; provide an explicit type_hint")


def _go_quote(value):
    if any(0xD800 <= ord(c) <= 0xDFFF for c in value):
        _fail("unsupported_literal", "Go strings cannot contain lone Unicode surrogates")
    # ASCII escapes avoid raw line separators; Go needs a single \U escape for
    # non-BMP codepoints rather than JSON's UTF-16 surrogate pair spelling.
    result = json.dumps(value, ensure_ascii=False)
    return result.replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")


def _go_emit(value, hint, specification):
    typ = type(value)
    kind = specification[0]
    if value is None and kind in {"sequence", "map"}:
        if kind == "sequence" and specification[1] is not None:
            _fail("literal_type", "Go arrays cannot be nil")
        return "nil"
    if kind == "atom":
        name = specification[1]
        if name in {"any", "interface{}"}:
            if value is None:
                return "nil"
            inferred = _go_infer(value)
            return _go_emit(value, inferred, _go_type(inferred))
        if name == "string" and typ is str:
            return _go_quote(value)
        if name == "bool" and typ is bool:
            return "true" if value else "false"
        if name.startswith("float") and typ in {int, float}:
            try:
                number = float(value)
                represented = struct.unpack('f', struct.pack('f', number))[0] if name == 'float32' else number
            except (OverflowError, struct.error):
                _fail("literal_type", f"Value is outside Go {name} range")
            if not math.isfinite(represented) or represented != value:
                _fail("literal_type", f"Value is not exactly representable as Go {name}")
            return repr(number)
        if name not in {"string", "bool", "float32", "float64"} and typ is int:
            unsigned = name.startswith("uint") or name == "byte"
            match = re.search(r"(\d+)$", name)
            bits = int(match.group(1)) if match else (8 if name == "byte" else 32 if name == "rune" else 64)
            if not (0 <= value < 2 ** bits if unsigned else -(2 ** (bits - 1)) <= value < 2 ** (bits - 1)):
                _fail("literal_type", f"Integer is outside Go {name} range")
            return str(value)
        _fail("literal_type", f"Value does not match Go {name}")
    if kind == "sequence":
        if typ not in {list, bytes}:
            _fail("literal_type", "Go slice/array requires a list or bytes value")
        size, child = specification[1:]
        if size is not None and size != len(value):
            _fail("literal_type", "Go array length does not match expected value")
        child_hint = hint[hint.index("]") + 1:]
        return hint + "{" + ", ".join(_go_emit(v, child_hint, child) for v in value) + "}"
    if kind == "map":
        if typ is not dict:
            _fail("literal_type", "Go map requires a dictionary value")
        key_spec, val_spec = specification[1:]
        key_hint = hint[4:hint.index("]")]
        value_hint = hint[hint.index("]") + 1:]
        return hint + "{" + ", ".join(
            _go_emit(k, key_hint, key_spec) + ": " + _go_emit(v, value_hint, val_spec)
            for k, v in value.items()) + "}"
    _fail("literal_type", "Unsupported Go literal type")


def emit_literal(value: Any, language: str, type_hint: str | None = None, *, limits: Limits = DEFAULT_LIMITS) -> str:
    """Emit a closed literal, rejecting ambiguous/unrepresentable target values."""
    value = _copy_value(value, limits)
    if language == "python":
        return _python_literal(value)
    if language == "go":
        if value is None and type_hint is None:
            return "nil"
        hint = type_hint or _go_infer(value)
        if len(hint) > limits.expression_bytes or hint.count("[") > limits.depth:
            _fail("literal_type", "Go type hint exceeds the structural budget")
        return _go_emit(value, hint, _go_type(hint))
    if language not in {"typescript", "javascript", "ts"}:
        _fail("unsupported_language", f"Unsupported output language: {language}")

    def emit(v):
        typ = type(v)
        if v is None:
            return "null"
        if typ is bool:
            return "true" if v else "false"
        if typ is int:
            if abs(v) > 2 ** 53 - 1:
                _fail("literal_type", "Integer is not exactly representable as a JavaScript Number")
            return str(v)
        if typ is float:
            return repr(v)
        if typ is str:
            return json.dumps(v, ensure_ascii=True)
        if typ in {list, tuple}:
            return "[" + ", ".join(emit(x) for x in v) + "]"
        if typ is dict:
            if any(type(k) is not str for k in v):
                _fail("literal_type", "JavaScript object literal requires string keys")
            # Computed property spelling keeps __proto__ as a data property.
            return "{" + ", ".join("[" + emit(k) + "]: " + emit(x) for k, x in v.items()) + "}"
        _fail("unsupported_literal", f"Cannot emit {typ.__name__} as a JavaScript literal")

    return emit(value)


def _json_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            _fail("duplicate_key", f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def parse_completions(payload: str | dict, candidates: list[dict], *, limits: Limits = DEFAULT_LIMITS) -> dict[str, dict]:
    """Strict, all-or-nothing protocol parsing before any completion is admitted."""
    ids = set()
    for candidate in candidates:
        cid = candidate.get("candidate_id")
        if type(cid) is not str or not cid or cid in ids:
            _fail("candidate_schema", "Program candidate IDs must be unique nonempty strings")
        ids.add(cid)
    if type(payload) is str:
        if len(payload.encode("utf-8", "surrogatepass")) > limits.payload_bytes:
            _fail("payload_budget", "Model response exceeds the byte budget")
        try:
            payload = json.loads(payload, object_pairs_hook=_json_pairs,
                                 parse_constant=lambda _: _fail("invalid_json", "Non-finite JSON constants are forbidden"))
        except (json.JSONDecodeError, RecursionError) as exc:
            _fail("invalid_json", f"Cannot parse model response: {type(exc).__name__}")
    if type(payload) is not dict or set(payload) != {"completions"} or type(payload["completions"]) is not list:
        _fail("completion_schema", "Response must contain only a completions array")
    if len(payload["completions"]) > limits.completions:
        _fail("payload_budget", "Too many completions")
    result = {}
    by_id = {candidate["candidate_id"]: candidate for candidate in candidates}
    for row in payload["completions"]:
        if type(row) is not dict or set(row) != {"candidate_id", "observe", "expected", "guard"}:
            _fail("completion_schema", "Each completion requires only candidate_id, observe, expected, guard")
        cid = row["candidate_id"]
        if type(cid) is not str or cid not in ids:
            _fail("unknown_candidate", "Completion refers to an unoffered candidate ID")
        if cid in result:
            _fail("duplicate_completion", f"Duplicate completion for {cid}")
        index = row["observe"]
        observations = by_id[cid].get("observations", [])
        if type(index) is not int or not 0 <= index < len(observations):
            _fail("observation_index", f"Observation is not an offered index for {cid}")
        if type(row["expected"]) is not str or (row["guard"] is not None and type(row["guard"]) is not str):
            _fail("completion_schema", "Expected must be an expression string; guard must be a string or null")
        result[cid] = row
    return result


def _source_slots(values, limits):
    if type(values) not in {list, tuple}:
        _fail("candidate_schema", "Source slots must be arrays")
    return [_copy_value(decode_value(v, limits=limits), limits) for v in values]


def _check_type(value, observation):
    hint = observation.get("type") if type(observation) is dict else None
    known = {"str": str, "string": str, "bool": bool, "boolean": bool,
             "int": int, "integer": int, "float": float, "list": list,
             "array": list, "tuple": tuple, "dict": dict, "object": dict,
             "set": set, "bytes": bytes, "null": type(None), "None": type(None)}
    if hint in known and type(value) is not known[hint]:
        _fail("observation_type", f"Expected value does not match observation type {hint}")
    if hint == "number" and type(value) not in {int, float}:
        _fail("observation_type", "Expected value does not match observation type number")


def validate_completions(payload: str | dict, candidates: list[dict], *, limits: Limits = DEFAULT_LIMITS) -> dict:
    """Return accepted absolute oracles and explicit rejection reasons.

    Each accepted row has ``value`` (tagged JSON), ``literal``, dependency flags,
    and witness counts. A false guard rejects the candidate, never emits skip.
    Missing completions reject. Invalid protocol rejects the complete response.
    ``witnesses_checked`` counts only supplied, applicable observations; this is
    evidence of non-refutation, not proof of the proposed semantic relation.
    """
    try:
        parsed = parse_completions(payload, candidates, limits=limits)
    except OracleError as exc:
        return {"accepted": [], "rejected": [
            {"candidate_id": c.get("candidate_id"), "code": exc.code, "reason": exc.reason}
            for c in candidates], "protocol_error": {"code": exc.code, "reason": exc.reason}}
    accepted, rejected = [], []
    for candidate in candidates:
        cid = candidate["candidate_id"]
        row = parsed.get(cid)
        try:
            if row is None:
                _fail("missing_completion", "No semantic completion was supplied for this candidate")
            pre = _source_slots(candidate.get("pre", []), limits)
            arg = _source_slots(candidate.get("arg", []), limits)
            expected, guard = row["expected"], row["guard"]
            # Validate expected even when a guard is false, so dormant unsafe code
            # cannot be accepted by moving it behind a guard or conditional.
            dependencies = expression_dependencies(expected, limits=limits)
            if guard is not None:
                truth = evaluate_expression(guard, pre, arg, limits=limits)
                if type(truth) is not bool:
                    _fail("guard_type", "Guard expression must evaluate to a boolean")
                if not truth:
                    _fail("guard_false", "Source expected values and inputs do not satisfy the guard")
            value = evaluate_expression(expected, pre, arg, limits=limits)
            observation = candidate["observations"][row["observe"]]
            _check_type(value, observation)
            checked, inapplicable = 0, 0
            for witness in candidate.get("witnesses", []):
                if witness.get("observe", row["observe"]) != row["observe"]:
                    continue
                wp = _source_slots(witness.get("pre", []), limits)
                wa = _source_slots(witness.get("arg", []), limits)
                after = _copy_value(decode_value(witness["after"], limits=limits), limits)
                if guard is not None:
                    applicable = evaluate_expression(guard, wp, wa, limits=limits)
                    if type(applicable) is not bool:
                        _fail("guard_type", "Witness guard must evaluate to a boolean")
                    if not applicable:
                        inapplicable += 1
                        continue
                predicted = evaluate_expression(expected, wp, wa, limits=limits)
                if not same_value(predicted, after):
                    _fail("witness_refuted", "Proposed relation contradicts a supplied source expectation witness")
                checked += 1
            hint = observation.get("go_type") if type(observation) is dict else None
            if candidate.get("expected_template") is not None:
                from .expected_templates import render_template
                literal = render_template(candidate["expected_template"], value, candidate.get("language", "python"), limits=limits)
            else:
                literal = emit_literal(value, candidate.get("language", "python"),
                                       hint or candidate.get("type_hint"), limits=limits)
            accepted.append({"candidate_id": cid, "observe": row["observe"],
                             "expected_expr": expected, "guard_expr": guard,
                             "value": encode_value(value, limits=limits), "literal": literal,
                             **dependencies, "witnesses_checked": checked,
                             "witnesses_inapplicable": inapplicable,
                             "oracle_mode": "source_expected_template" if candidate.get("expected_template") is not None else "absolute_from_source_values"})
        except OracleError as exc:
            rejected.append({"candidate_id": cid, "code": exc.code, "reason": exc.reason})
        except (KeyError, TypeError, ValueError) as exc:
            rejected.append({"candidate_id": cid, "code": "candidate_schema", "reason": str(exc)})
    return {"accepted": accepted, "rejected": rejected}
