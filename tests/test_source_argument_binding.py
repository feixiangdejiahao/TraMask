"""Argument correspondence fixtures; no miniature subject is executed."""
from __future__ import annotations

import ast
import inspect

import pytest

from anchor_retrieval.syntax import Source, units
from prototypes.source_argument_binding import bind_python_arguments
from relational_gap.frontend import _parameters


def parameters(signature):
    source = Source("library.py", "def compute(" + signature + "):\n    return value\n", "python")
    found, _ = units(source)
    return _parameters(found[0])


def independent_signature(signature):
    """Use Python's own AST, independently of frontend parameter records."""
    function = ast.parse("def compute(" + signature + "):\n    pass\n").body[0]
    args = function.args
    regular = [*args.posonlyargs, *args.args]
    default_count = len(args.defaults)
    rows = []
    for i, arg in enumerate(regular):
        kind = inspect.Parameter.POSITIONAL_ONLY if i < len(args.posonlyargs) else inspect.Parameter.POSITIONAL_OR_KEYWORD
        default = 0 if i >= len(regular) - default_count else inspect.Parameter.empty
        rows.append(inspect.Parameter(arg.arg, kind, default=default))
    if args.vararg:
        rows.append(inspect.Parameter(args.vararg.arg, inspect.Parameter.VAR_POSITIONAL))
    for arg, default_node in zip(args.kwonlyargs, args.kw_defaults):
        default = 0 if default_node is not None else inspect.Parameter.empty
        rows.append(inspect.Parameter(arg.arg, inspect.Parameter.KEYWORD_ONLY, default=default))
    if args.kwarg:
        rows.append(inspect.Parameter(args.kwarg.arg, inspect.Parameter.VAR_KEYWORD))
    return inspect.Signature(rows)


@pytest.mark.parametrize("signature,positional,keywords,receiver", [
    ("value, other", [11, 22], [], None),
    ("value, other", [11], [("other", 22)], None),
    ("value, other", [], [("other", 22), ("value", 11)], None),
    ("value, /, other", [11], [("other", 22)], None),
    ("value, /, other", [], [("value", 11), ("other", 22)], None),
    ("*, value", [], [("value", 11)], None),
    ("*, value", [11], [], None),
    ("value, *, flag", [11], [("flag", 22)], None),
    ("value, *, flag", [11, 22], [], None),
    ("value=0, *, flag=1", [11], [("flag", 22)], None),
    ("value, other=1", [11, 22], [], None),
    ("value, other=1", [11], [("other", 22)], None),
    ("value, other=1", [11], [], None),
    ("value", [11], [("value", 22)], None),
    ("value", [11], [("unknown", 22)], None),
    ("value", [11, 22], [], None),
    ("value", [], [], None),
    ("receiver, value", [11], [], 0),
    ("receiver, value", [], [("value", 11)], 0),
    ("receiver, /, value", [], [("value", 11)], 0),
    ("receiver, value", [11], [("receiver", 22)], 0),
    ("*, receiver, value", [], [("value", 11)], 0),
    ("", [], [], None),
    ("", [], [], 0),
])
def test_binding_agrees_with_python_signature_when_every_formal_is_supplied(
        signature, positional, keywords, receiver):
    rows = parameters(signature)
    reference = independent_signature(signature)
    supplied = [*([receiver] if receiver is not None else []), *positional]
    try:
        result = reference.bind(*supplied, **dict(keywords))
        complete = set(result.arguments) == set(reference.parameters)
    except TypeError:
        result, complete = None, False
    actual = bind_python_arguments(rows, positional, keywords, implicit_receiver=receiver)
    assert (actual["status"] == "bound") == complete
    assert actual["bindings"] == (dict(result.arguments) if complete else {})


@pytest.mark.parametrize("signature,positionals,keywords,receiver,reason", [
    ("*, value", [11], [], None, "excess_positional_arguments"),
    ("owner, *, value", [11], [], 0, "excess_positional_arguments"),
    ("*, owner, value", [], [("value", 11)], 0, "implicit_receiver_keyword_only_formal"),
    ("value, /", [], [("value", 11)], None, "positional_only_supplied_as_keyword"),
    ("value", [], [("value", 11), ("value", 22)], None, "duplicate_keyword_argument"),
    ("value", [11], [("value", 22)], None, "duplicate_argument_binding"),
    ("value", [11], [("missing", 22)], None, "unknown_keyword_argument"),
    ("value=explode()", [], [], None, "omitted_formal_not_supported"),
    ("*values", [], [], None, "variadic_formals_not_supported"),
    ("**values", [], [], None, "variadic_formals_not_supported"),
    ("value, *others", [11], [], None, "variadic_formals_not_supported"),
])
def test_invalid_and_unsupported_calls_never_leak_partial_bindings(
        signature, positionals, keywords, receiver, reason):
    assert bind_python_arguments(parameters(signature), positionals, keywords,
                                 implicit_receiver=receiver) == {
        "status": "unknown", "bindings": {}, "reason": reason}


def test_default_expression_is_not_evaluated_when_explicitly_supplied():
    result = bind_python_arguments(parameters("value=explode()"), [0])
    assert result == {"status": "bound", "bindings": {"value": 0}, "reason": None}


def test_implicit_receiver_formal_is_retained_with_arbitrary_spelling():
    result = bind_python_arguments(parameters("object_arg, value"), [],
                                   [("value", 11)], implicit_receiver=22)
    assert result["bindings"] == {"object_arg": 22, "value": 11}


def test_staticmethod_like_call_keeps_first_explicit_formal_even_when_named_self():
    result = bind_python_arguments(parameters("self"), [11])
    assert result["bindings"] == {"self": 11}


@pytest.mark.parametrize("keywords", [[("value", 11)], []])
def test_spread_flag_always_blocks_exact_binding(keywords):
    result = bind_python_arguments(parameters("value"), [], keywords, has_spread=True)
    assert result == {"status": "unknown", "bindings": {},
                      "reason": "spread_arguments_not_supported"}


@pytest.mark.parametrize("rows,positional,keywords,receiver", [
    ([{"name": None}], [], [], None),
    ([{"name": "value"}, {"name": "value"}], [11, 22], [], None),
    ([{"name": "value", "positional_only": True, "keyword_only": True}], [11], [], None),
    ([{"name": "value"}], [True], [], None),
    ([{"name": "value"}], [-1], [], None),
    ([{"name": "value"}], [], [("value", None)], None),
    ([{"name": "value"}], [], ["value"], None),
    ([{"name": "value"}], [11], [], True),
])
def test_malformed_records_stay_unknown(rows, positional, keywords, receiver):
    result = bind_python_arguments(rows, positional, keywords, implicit_receiver=receiver)
    assert result["status"] == "unknown"
    assert result["bindings"] == {}


def test_keyword_pairs_can_be_ordered_iterators_without_losing_duplicates():
    rows = parameters("value, other")
    result = bind_python_arguments(iter(rows), iter([]), iter([("other", 22), ("value", 11)]))
    assert result["bindings"] == {"value": 11, "other": 22}
    duplicate = bind_python_arguments(rows, [], iter([("value", 11), ("value", 22)]))
    assert duplicate["status"] == "unknown"
    assert duplicate["reason"] == "duplicate_keyword_argument"
