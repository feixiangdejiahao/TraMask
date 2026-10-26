"""Literal-leaf templates of a source-owned expected expression.

This module never evaluates source expressions.  Only explicitly supported
syntax shapes are traversed.  Constructor names, bindings, keys, subscripts,
container delimiters, type wrappers, and all unsupported expressions remain
source text.  A completion supplies an ordered vector of primitive values.
"""
from __future__ import annotations

from typing import Any

from prototypes.test_action_and_oracle_transfer.oracle import (
    DEFAULT_LIMITS, Limits, OracleError, decode_value, emit_literal,
    encode_value, parse_source_literal,
)


_PRIMITIVES = {str, bytes, int, float, bool, type(None)}
_LANGUAGES = {"python", "go", "typescript"}
_ATOMS = {
    "python": {"integer", "float", "string", "concatenated_string", "true", "false", "none"},
    "go": {"int_literal", "float_literal", "interpreted_string_literal", "raw_string_literal", "true", "false", "nil"},
    "typescript": {"number", "string", "true", "false", "null"},
}
_CONTAINERS = {
    "python": {"list", "tuple", "set", "dictionary"},
    "go": {"literal_value"},
    "typescript": {"array", "object"},
}
_CALLS = {"call", "call_expression", "new_expression"}
_PAIRS = {"pair", "keyed_element", "keyword_argument"}
_UNARY = {"unary_operator", "unary_expression"}
_WRAPPERS = {"parenthesized_expression", "literal_element"}


def _fail(code: str, reason: str):
    raise OracleError(code, reason)


def _language(language: str) -> str:
    result = {"ts": "typescript", "javascript": "typescript"}.get(language, language)
    if result not in _LANGUAGES:
        _fail("expected_template", "Unsupported expected-template language")
    return result


def _span(span) -> tuple[int, int]:
    if isinstance(span, dict):
        start, end = span.get("start_byte"), span.get("end_byte")
    elif isinstance(span, (tuple, list)) and len(span) == 2:
        start, end = span
    else:
        start, end = getattr(span, "start_byte", None), getattr(span, "end_byte", None)
    if type(start) is not int or type(end) is not int or start < 0 or end <= start:
        _fail("expected_template", "Expected span must be a nonempty byte interval")
    return start, end


def _budget_tree(node, limits: Limits):
    pending, count = [(node, 0)], 0
    while pending:
        current, depth = pending.pop()
        count += 1
        if count > limits.expression_nodes or depth > limits.depth:
            _fail("template_budget", "Expected template exceeds the AST budget")
        if current.is_error or current.is_missing:
            _fail("expected_template", "Expected expression contains a syntax error")
        pending.extend((child, depth + 1) for child in current.children)


def _exact_node(root, start: int, end: int):
    # Only descend the containing path; do not scan the entire source file.
    current, exact = root, None
    while current is not None:
        if current.start_byte == start and current.end_byte == end:
            exact = current
        current = next((child for child in current.named_children
                        if child.start_byte <= start and child.end_byte >= end), None)
    if exact is None:
        _fail("expected_template", "Expected span must cover one complete expression")
    return exact


def extract_template(source, span, *, limits: Limits = DEFAULT_LIMITS,
                     min_holes: int = 2, max_holes: int = 64) -> dict[str, Any]:
    """Return a template with at least ``min_holes`` primitive value holes.

    ``source`` is an ``anchor_retrieval.syntax.Source`` (or equivalent object
    with ``data``, ``root``, and ``language``).  ``span`` may be a byte-span
    dictionary, a two-item sequence, or a tree-sitter node.  Hole intervals
    are relative to the returned ``text`` and values use ``encode_value``.

    Numeric unary signs form part of their hole.  Keys (including computed
    keys), field names, call targets, splats, subscripts, and unknown syntax
    are fixed.  Empty containers stay fixed.  Go rune literals and TS
    template literals are conservatively fixed because their source types
    or escaping are not represented by the common scalar emitter.
    """
    language = _language(source.language)
    start, end = _span(span)
    if type(min_holes) is not int or min_holes < 1 or type(max_holes) is not int or max_holes < min_holes:
        _fail("template_budget", "Template hole bounds must satisfy 1 <= min_holes <= max_holes")
    data = source.data
    if end > len(data):
        _fail("expected_template", "Expected span lies outside its source")
    raw = data[start:end]
    if len(raw) > limits.expression_bytes:
        _fail("template_budget", "Expected template exceeds the byte budget")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        _fail("expected_template", "Expected span splits a UTF-8 character")
    # Keep any surrounding whitespace verbatim, but require the interior to
    # be a complete AST expression rather than a partial textual fragment.
    left = len(raw) - len(raw.lstrip())
    right = len(raw.rstrip())
    node = _exact_node(source.root, start + left, start + right)
    _budget_tree(node, limits)
    allowed_roots = (_CONTAINERS[language] | _CALLS |
                     _WRAPPERS | {"composite_literal", "as_expression", "satisfies_expression"})
    if language == "go" and node.type == "unary_expression":
        operator = node.child_by_field_name("operator")
        if operator is not None and data[operator.start_byte:operator.end_byte] == b"&":
            allowed_roots.add("unary_expression")
    if node.type not in allowed_roots:
        _fail("expected_template", "Expected span is not a supported expression shape")
    holes: list[dict[str, Any]] = []

    def add(current):
        value = parse_source_literal(data[current.start_byte:current.end_byte].decode("utf-8"),
                                     language, limits=limits)
        if type(value) not in _PRIMITIVES:
            return
        if len(holes) >= max_holes:
            _fail("template_budget", "Expected template exceeds the hole budget")
        hint = None
        # Go untyped integers can represent uint64 values that the default
        # signed-int emitter rejects.  The hint affects validation only;
        # the original constructor/type wrappers remain source-owned text.
        if language == "go" and type(value) is int and value >= 2 ** 63:
            hint = "uint64"
        emit_literal(value, language, hint, limits=limits)
        hole = {"start_byte": current.start_byte - start,
                "end_byte": current.end_byte - start,
                "value": encode_value(value, limits=limits),
                "value_type": type(value).__name__}
        if hint is not None:
            hole["type_hint"] = hint
        holes.append(hole)

    def visit(current):
        kind = current.type
        if kind in _ATOMS[language]:
            # Never descend into a string, including interpolated strings.
            add(current)
        elif kind in _UNARY:
            operator = current.child_by_field_name("operator")
            spelling = data[operator.start_byte:operator.end_byte] if operator is not None else b""
            if spelling in {b"+", b"-"}:
                # Unknown signed operands stay fixed; no unsigned child hole.
                add(current)
            elif language == "go" and spelling == b"&":
                operand = current.child_by_field_name("operand")
                if operand is not None and operand.type in {"composite_literal", "parenthesized_expression"}:
                    visit(operand)
        elif kind in _PAIRS:
            value = current.child_by_field_name("value")
            if value is not None:
                visit(value)
        elif kind in _CALLS:
            arguments = current.child_by_field_name("arguments")
            if arguments is not None:
                for argument in arguments.named_children:
                    visit(argument)
        elif kind == "composite_literal" and language == "go":
            body = current.child_by_field_name("body")
            if body is not None:
                visit(body)
        elif kind in _CONTAINERS[language] or kind in _WRAPPERS:
            for item in current.named_children:
                visit(item)
        elif language == "typescript" and kind in {"as_expression", "satisfies_expression"}:
            if current.named_children:
                visit(current.named_children[0])
        # Everything else (identifiers, operators, subscripts, comprehensions,
        # spread expressions, function bodies, type syntax) is left intact.

    visit(node)
    holes.sort(key=lambda hole: hole["start_byte"])
    if len(holes) < min_holes:
        _fail("expected_template", f"Expected template requires at least {min_holes} primitive value holes")
    template = {"text": text, "language": language, "holes": holes}
    _validate(template, language, limits, max_holes)
    return template


def _validate(template, language: str, limits: Limits, max_holes: int):
    if type(template) is not dict or type(template.get("text")) is not str:
        _fail("expected_template", "Malformed expected template")
    if _language(template.get("language", language)) != language:
        _fail("expected_template", "Template and output languages differ")
    try:
        raw = template["text"].encode("utf-8")
    except UnicodeEncodeError:
        _fail("expected_template", "Expected template is not UTF-8 source text")
    if len(raw) > limits.expression_bytes:
        _fail("template_budget", "Expected template exceeds the byte budget")
    holes = template.get("holes")
    if type(holes) is not list or not 1 <= len(holes) <= max_holes:
        _fail("template_budget", "Expected template has an invalid hole count")
    values, previous_end = [], 0
    for hole in holes:
        if type(hole) is not dict:
            _fail("expected_template", "Malformed expected-template hole")
        start, end = _span(hole)
        if start < previous_end or end > len(raw):
            _fail("expected_template", "Expected-template holes overlap or are out of bounds")
        try:
            original_text = raw[start:end].decode("utf-8")
            raw[:start].decode("utf-8")
        except UnicodeDecodeError:
            _fail("expected_template", "Expected-template hole splits a UTF-8 character")
        original = decode_value(hole.get("value"), limits=limits)
        if type(original) not in _PRIMITIVES:
            _fail("expected_template", "Expected-template holes must contain primitive values")
        parsed = parse_source_literal(original_text, language, limits=limits)
        if type(parsed) is not type(original) or parsed != original:
            _fail("expected_template", "Expected-template hole value differs from its source")
        if hole.get("value_type", type(original).__name__) != type(original).__name__:
            _fail("expected_template", "Expected-template hole type metadata differs from its value")
        values.append(original)
        previous_end = end
    return raw, holes, values


def render_template(template, values, language: str, *, limits: Limits = DEFAULT_LIMITS,
                    max_holes: int = 64) -> str:
    """Fill a trusted source template with an already-decoded value vector.

    Exact primitive types and arity must match the original vector.  Literal
    emission, source interval checks, and bounds are applied before output.
    ``values`` is an actual Python list/tuple, not a JSON-tagged container.
    """
    language = _language(language)
    raw, holes, originals = _validate(template, language, limits, max_holes)
    if type(values) not in {list, tuple} or len(values) != len(holes):
        _fail("template_arity", "Completion must return exactly one value per expected-template hole")
    pieces, cursor, output_size = [], 0, 0
    for hole, original, value in zip(holes, originals, values):
        if type(value) is not type(original):
            _fail("template_type", "Completion changed an expected-template hole's exact primitive type")
        literal = emit_literal(value, language, hole.get("type_hint"), limits=limits).encode("utf-8")
        fixed = raw[cursor:hole["start_byte"]]
        pieces.extend((fixed, literal))
        output_size += len(fixed) + len(literal)
        if output_size > limits.expression_bytes:
            _fail("template_budget", "Rendered expected template exceeds the byte budget")
        cursor = hole["end_byte"]
    pieces.append(raw[cursor:])
    if output_size + len(pieces[-1]) > limits.expression_bytes:
        _fail("template_budget", "Rendered expected template exceeds the byte budget")
    return b"".join(pieces).decode("utf-8")
