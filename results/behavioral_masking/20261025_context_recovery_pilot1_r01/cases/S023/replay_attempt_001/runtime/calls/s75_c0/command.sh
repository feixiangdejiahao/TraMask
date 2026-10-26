cd /app && cat > tests/test_partial.py <<'PYEOF'
from __future__ import annotations

from dataclasses import dataclass
from typing import List, TypedDict

import pytest
from attrs import define, field

import cattrs
import cattr
from cattrs import BaseConverter, Converter
from cattrs.errors import ClassValidationError, ForbiddenExtraKeysError
from cattrs.partial import PartialResult


@define
class Inner:
    x: int
    y: str = "hello"


@define
class Outer:
    inner: Inner
    z: int = 5
    items: List[int] = field(factory=list)


@define
class InnerPartial:
    x: int
    y: str = "default"


@define
class OuterPartial:
    inner: InnerPartial
    z: int


@define
class InnerRequired:
    x: int
    y: int


@define
class OuterRequired:
    inner: InnerRequired
    z: int


@pytest.fixture
def converter():
    return Converter()


def test_exports():
    assert hasattr(cattrs, "partial_structure")
    assert hasattr(cattrs, "PartialResult")
    assert hasattr(cattr, "partial_structure")
    assert hasattr(cattr, "PartialResult")


def test_complete(converter):
    res = converter.partial_structure(
        {"inner": {"x": 1, "y": "hi"}, "z": 3, "items": [1, 2]}, Outer
    )
    assert res.value == Outer(Inner(1, "hi"), 3, [1, 2])
    assert res.is_complete is True
    assert res.structured_fields == frozenset({"inner", "z", "items"})
    assert res.failed_fields == frozenset()
    assert res.errors is None
    assert res.error_map == {}


def test_absent_fields_are_failed(converter):
    res = converter.partial_structure({"inner": {"x": 1}}, Outer)
    assert res.value == Outer(Inner(1))
    assert res.is_complete is False
    assert res.structured_fields == frozenset()
    assert res.failed_fields == frozenset({"inner", "z", "items"})
    # Absent fields don't have exceptions.
    assert res.error_map == {}
    assert res.errors is None


def test_required_missing_value_none(converter):
    @define
    class A:
        a: int
        b: str

    res = converter.partial_structure({"a": 1}, A)
    assert res.value is None
    assert res.structured_fields == frozenset({"a"})
    assert res.failed_fields == frozenset({"b"})
    assert res.error_map == {}


def test_field_failure(converter):
    @define
    class A:
        a: int
        b: int = 1

    res = converter.partial_structure({"a": "not an int"}, A)
    # `a` is required and failed, so no value can be produced.
    assert res.value is None
    assert res.structured_fields == frozenset({"b"})
    assert res.failed_fields == frozenset({"a"})
    assert res.errors is not None
    assert "a" in res.error_map


def test_nested_partial_uses_partial_value(converter):
    res = converter.partial_structure({"inner": {"x": 1}, "z": 5}, OuterPartial)
    assert res.value == OuterPartial(InnerPartial(1), 5)
    assert res.structured_fields == frozenset({"z"})
    assert res.failed_fields == frozenset({"inner"})


def test_nested_no_value_is_normal_failure(converter):
    res = converter.partial_structure({"inner": {"x": 1}, "z": 5}, OuterRequired)
    assert res.value is None
    assert res.structured_fields == frozenset({"z"})
    assert res.failed_fields == frozenset({"inner"})


def test_dataclass(converter):
    @dataclass
    class A:
        a: int
        b: str = "hi"

    res = converter.partial_structure({"a": 2}, A)
    assert res.value == A(2)
    assert res.failed_fields == frozenset({"b"})


def test_typeddict_required(converter):
    class TD(TypedDict):
        a: int
        b: str

    res = converter.partial_structure({"a": 1}, TD)
    assert res.value is None
    assert res.structured_fields == frozenset({"a"})
    assert res.failed_fields == frozenset({"b"})


def test_typeddict_optional(converter):
    class TDOpt(TypedDict, total=False):
        a: int
        b: str

    res = converter.partial_structure({"a": 1}, TDOpt)
    assert res.value == {"a": 1}
    assert res.structured_fields == frozenset({"a"})
    assert res.failed_fields == frozenset({"b"})

    res = converter.partial_structure({}, TDOpt)
    assert res.value == {}
    assert res.failed_fields == frozenset({"a", "b"})


def test_collections_atomic(converter):
    @define
    class A:
        items: List[int]
        mapping: dict[str, int]

    res = converter.partial_structure({"items": [1, "bad"], "mapping": {"a": 1}}, A)
    assert res.value is None
    assert res.structured_fields == frozenset({"mapping"})
    assert res.failed_fields == frozenset({"items"})
    assert "items" in res.error_map


def test_init_false_excluded(converter):
    @define
    class A:
        x: int
        computed: int = field(init=False, default=10)

    res = converter.partial_structure({"x": 1}, A)
    assert res.value == A(1)
    assert res.is_complete is True
    assert res.structured_fields == frozenset({"x"})
    assert res.failed_fields == frozenset()


def test_forbid_extra_keys():
    converter = Converter(forbid_extra_keys=True)

    @define
    class A:
        x: int
        y: int = 1

    res = converter.partial_structure({"x": 2, "extra": 3}, A)
    assert res.value == A(2)
    assert res.is_complete is False
    assert res.failed_fields == frozenset({"y"})
    assert res.errors is not None
    assert any(
        isinstance(exc, ForbiddenExtraKeysError)
        for exc in getattr(res.errors, "exceptions", (res.errors,))
    )


def test_detailed_validation_off():
    converter = Converter(detailed_validation=False)

    @define
    class A:
        x: int
        y: int = 1

    res = converter.partial_structure({"x": "bad"}, A)
    assert res.value == A(1)
    assert res.failed_fields == frozenset({"x"})
    assert res.errors is not None
    assert "x" in res.error_map


def test_detailed_validation_on(converter):
    @define
    class A:
        x: int
        y: int = 1

    res = converter.partial_structure({"x": "bad"}, A)
    assert isinstance(res.errors, ClassValidationError)


def test_refine(converter):
    @define
    class A:
        x: int
        y: str = "default"

    res = converter.partial_structure({"x": 1}, A)
    assert res.value == A(1)
    assert res.failed_fields == frozenset({"y"})

    res2 = res.refine({"y": "hello"})
    assert res2.value == A(1, "hello")
    assert res2.is_complete is True
    assert res2.structured_fields == frozenset({"x", "y"})
    assert res2.failed_fields == frozenset()


def test_refine_preserves_structured_fields(converter):
    @define
    class A:
        x: int
        y: str = "default"

    res = converter.partial_structure({"x": 1}, A)
    res2 = res.refine({"x": 100, "y": "hello"})
    assert res2.value == A(1, "hello")


def test_refine_nested(converter):
    res = converter.partial_structure({"inner": {"x": 1}, "z": 5}, OuterPartial)
    assert res.value == OuterPartial(InnerPartial(1), 5)
    assert res.failed_fields == frozenset({"inner"})

    res2 = res.refine({"inner": {"y": "world"}})
    assert res2.value == OuterPartial(InnerPartial(1, "world"), 5)
    assert res2.is_complete is True


def test_base_converter():
    @define
    class A:
        x: int
        y: str = "d"

    bc = BaseConverter()
    res = bc.partial_structure({"x": 1}, A)
    assert res.value == A(1)
    assert res.failed_fields == frozenset({"y"})


def test_top_level():
    @define
    class A:
        x: int
        y: str = "d"

    res = cattrs.partial_structure({"x": 1}, A)
    assert isinstance(res, PartialResult)
    assert res.value == A(1)
    res = cattr.partial_structure({"x": 1}, A)
    assert res.value == A(1)


def test_use_alias():
    @define
    class A:
        x: int
        y: int = field(alias="yy")

    converter = Converter(use_alias=True)
    res = converter.partial_structure({"x": 1, "yy": 2}, A)
    assert res.value == A(1, 2)
    assert res.is_complete is True
PYEOF
cd /app && timeout 30 python -m pytest tests/test_partial.py -q -o addopts="" 2>&1 | tail -30