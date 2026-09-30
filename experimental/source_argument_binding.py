"""Bind supplied Python source arguments without evaluating any expressions.

This module consumes ``relational_gap.frontend._parameters`` records and graph
value IDs.  The caller must already have proved the callee and, if supplied,
its implicit receiver binding.  Defaults are never evaluated or substituted:
every formal must have a supplied value.  No subject, model, or target data is
needed.  A bound result proves argument correspondence, not path feasibility,
types, effects, or the correctness of an expected value.
"""
from __future__ import annotations

from collections.abc import Mapping
import keyword


def _unknown(reason):
    # Never expose a partially guessed mapping on a failed binding.
    return {"status": "unknown", "bindings": {}, "reason": reason}


def _value_id(value):
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def bind_python_arguments(parameters, positional, keywords=(), *,
                          implicit_receiver=None, has_spread=False):
    """Return the complete formal-name -> supplied-value-ID mapping or unknown.

    ``keywords`` is an ordered iterable of ``(name, value_id)`` pairs rather
    than a dictionary, so duplicate source keywords cannot disappear.  Pass
    ``has_spread=True`` for any caller-side ``*args`` or ``**kwargs``.  Any
    variadic formal is unsupported, even when no extra actual is supplied.

    ``implicit_receiver`` is a value ID transported to the first formal only
    after the caller has proved ordinary/class-method descriptor binding.  A
    static method or an explicit unbound call must not supply this argument.
    """
    if has_spread:
        return _unknown("spread_arguments_not_supported")
    try:
        parameters = list(parameters)
        positional = list(positional)
        keywords = list(keywords)
    except TypeError:
        return _unknown("argument_records_not_iterable")
    names = []
    for parameter in parameters:
        if not isinstance(parameter, Mapping):
            return _unknown("unsupported_parameter_record")
        name = parameter.get("name")
        if (not isinstance(name, str) or not name.isidentifier()
                or keyword.iskeyword(name)):
            return _unknown("unsupported_unnamed_formal")
        if name in names:
            return _unknown("duplicate_formal_name")
        if parameter.get("variadic", False):
            return _unknown("variadic_formals_not_supported")
        if parameter.get("keyword_only", False) and parameter.get("positional_only", False):
            return _unknown("inconsistent_parameter_kind")
        names.append(name)
    if not all(_value_id(value) for value in positional):
        return _unknown("invalid_positional_value_id")
    actual_keywords = []
    seen_keywords = set()
    for item in keywords:
        if not isinstance(item, (tuple, list)) or len(item) != 2:
            return _unknown("unsupported_keyword_record")
        name, value = item
        if (not isinstance(name, str) or not name.isidentifier()
                or keyword.iskeyword(name) or not _value_id(value)):
            return _unknown("invalid_keyword_argument")
        if name in seen_keywords:
            return _unknown("duplicate_keyword_argument")
        seen_keywords.add(name)
        actual_keywords.append((name, value))

    bindings = {}
    explicit = parameters
    if implicit_receiver is not None:
        if not _value_id(implicit_receiver):
            return _unknown("invalid_implicit_receiver_value_id")
        if not parameters:
            return _unknown("implicit_receiver_without_formal")
        first = parameters[0]
        if first.get("keyword_only", False):
            return _unknown("implicit_receiver_keyword_only_formal")
        bindings[first["name"]] = implicit_receiver
        explicit = parameters[1:]
    positional_formals = [parameter for parameter in explicit
                          if not parameter.get("keyword_only", False)]
    if len(positional) > len(positional_formals):
        return _unknown("excess_positional_arguments")
    for parameter, value in zip(positional_formals, positional):
        bindings[parameter["name"]] = value
    by_name = dict(zip(names, parameters))
    for name, value in actual_keywords:
        if name not in by_name:
            return _unknown("unknown_keyword_argument")
        if by_name[name].get("positional_only", False):
            return _unknown("positional_only_supplied_as_keyword")
        if name in bindings:
            return _unknown("duplicate_argument_binding")
        bindings[name] = value
    if any(name not in bindings for name in names):
        return _unknown("omitted_formal_not_supported")
    # Formal order is deterministic, independent of keyword source order.
    return {"status": "bound", "bindings": {name: bindings[name] for name in names},
            "reason": None}
