"""Tests for partial structuring."""

from dataclasses import dataclass
from typing import Dict, List, Optional, TypedDict

import pytest
from attrs import define, field, fields

from cattrs import (
    BaseConverter,
    Converter,
    PartialResult,
    partial_structure,
)
from cattrs.errors import (
    AttributeValidationNote,
    ClassValidationError,
    ForbiddenExtraKeysError,
)


@define
class Child:
    x: int
    y: int = 0


@define
class Parent:
    name: str
    child: Child
    tags: List[int] = field(factory=list)
    desc: str = "none"


@dataclass
class ChildDC:
    x: int
    y: int = 0


@dataclass
class ParentDC:
    name: str
    child: ChildDC
    tags: List[int] = None  # type: ignore
    desc: str = "none"


class TD(TypedDict):
    a: int
    b: str


def test_exported():
    assert hasattr(partial_structure, "__call__")
    assert PartialResult is not None
    from cattrs import BaseConverter as BC

    assert hasattr(BC, "partial_structure")


def test_complete_attrs():
    c = Converter()
    r = c.partial_structure(
        {"name": "n", "child": {"x": 1, "y": 2}, "tags": [1, 2], "desc": "d"}, Parent
    )
    assert r.is_complete is True
    assert r.value == Parent("n", Child(1, 2), [1, 2], "d")
    assert r.structured_fields == frozenset({"name", "child", "tags", "desc"})
    assert r.failed_fields == frozenset()
    assert r.errors is None
    assert r.error_map == {}


def test_complete_baseconverter():
    c = BaseConverter()
    r = c.partial_structure({"name": "n", "child": {"x": 1, "y": 2}}, Parent)
    assert r.is_complete is False  # desc missing
    assert r.value.name == "n"
    assert r.value.child == Child(1, 2)
    assert "desc" in r.failed_fields


def test_missing_optional_uses_default():
    c = Converter()
    r = c.partial_structure({"name": "n", "child": {"x": 1}}, Parent)
    assert r.is_complete is False
    assert r.value is not None
    assert r.value.desc == "none"
    assert r.value.tags == []
    assert r.value.child == Child(1, 0)
    assert r.structured_fields == frozenset({"name"})
    assert r.failed_fields == frozenset({"child", "tags", "desc"})
    assert "child" in r.error_map
    assert isinstance(r.error_map["child"], ClassValidationError)


def test_missing_required_makes_value_none():
    c = Converter()
    r = c.partial_structure({"child": {"x": 1}}, Parent)
    assert r.value is None
    assert r.is_complete is False
    # child is partially complete (its optional y is missing) so the parent
    # marks it as failed even though its partial value is used.
    assert r.structured_fields == frozenset()
    assert "name" in r.failed_fields
    assert "child" in r.failed_fields
    assert isinstance(r.error_map["name"], KeyError)


def test_failed_field_with_default_uses_default():
    c = Converter()
    # tags is List[int]; "a" is invalid so the whole field fails and falls back
    # to its default factory.
    r = c.partial_structure(
        {"name": "n", "child": {"x": 1, "y": 2}, "tags": ["a"]}, Parent
    )
    assert r.value is not None
    assert r.value.tags == []
    assert "tags" in r.failed_fields
    assert "tags" not in r.structured_fields


def test_dataclass():
    c = Converter()
    r = c.partial_structure({"name": "n", "child": {"x": 1}}, ParentDC)
    assert r.value is not None
    assert r.value.name == "n"
    assert r.value.child == ChildDC(1, 0)
    assert "desc" in r.failed_fields
    assert "tags" in r.failed_fields


def test_typeddict():
    c = Converter()
    r = c.partial_structure({"a": 1}, TD)
    assert r.is_complete is False
    assert r.value == {"a": 1}
    assert r.structured_fields == frozenset({"a"})
    assert r.failed_fields == frozenset({"b"})
    assert isinstance(r.error_map["b"], KeyError)


def test_typeddict_complete():
    c = Converter()
    r = c.partial_structure({"a": 1, "b": "x"}, TD)
    assert r.is_complete is True
    assert r.value == {"a": 1, "b": "x"}
    assert r.errors is None


def test_nested_partial_marks_parent_failed():
    c = Converter()

    @define
    class A:
        a: int

    @define
    class B:
        inner: A
        other: int = 0

    r = c.partial_structure({"inner": {"a": 1}, "other": 5}, B)
    # inner is incomplete because A has no defaults and a is present -> complete.
    assert r.is_complete is True
    assert r.value == B(A(1), 5)

    # inner missing a -> no value -> normal failure
    r = c.partial_structure({"inner": {}, "other": 5}, B)
    assert r.value is None
    assert "inner" in r.failed_fields

    # inner with optional missing -> partial value used, parent failed
    @define
    class C2:
        inner: Child
        other: int = 0

    r = c.partial_structure({"inner": {"x": 1}, "other": 5}, C2)
    assert r.value == C2(Child(1, 0), 5)
    assert r.value.inner is not None
    assert "inner" in r.failed_fields
    assert "inner" not in r.structured_fields


def test_collection_atomic():
    c = Converter()

    @define
    class L:
        items: List[int]

    r = c.partial_structure({"items": ["a", 2]}, L)
    assert r.value is None
    assert "items" in r.failed_fields
    assert "items" not in r.structured_fields


def test_dict_atomic():
    c = Converter()

    @define
    class D:
        m: Dict[str, int]

    r = c.partial_structure({"m": {"a": "bad"}}, D)
    assert r.value is None
    assert "m" in r.failed_fields


def test_init_false_excluded():
    @define
    class I:
        a: int
        b: int = field(init=False, default=5)

    c = Converter()
    r = c.partial_structure({"a": 1}, I)
    assert r.value == I(1)
    assert r.structured_fields == frozenset({"a"})
    assert r.failed_fields == frozenset()

    # even when present, init=False fields aren't tracked
    r = c.partial_structure({"a": 1, "b": 7}, I)
    assert r.value.b == 7
    assert r.structured_fields == frozenset({"a"})
    assert r.failed_fields == frozenset()


def test_forbid_extra_keys():
    c = Converter(forbid_extra_keys=True)
    r = c.partial_structure(
        {"name": "n", "child": {"x": 1, "y": 2}, "extra": 1}, Parent
    )
    assert r.value is not None
    assert r.is_complete is False
    assert "extra" not in r.failed_fields
    assert r.failed_fields == frozenset({"tags", "desc"})


def test_forbid_extra_keys_complete_still_incomplete():
    c = Converter(forbid_extra_keys=True)
    data = {
        "name": "n",
        "child": {"x": 1, "y": 2},
        "tags": [],
        "desc": "d",
        "extra": 1,
    }
    r = c.partial_structure(data, Parent)
    assert r.value == Parent("n", Child(1, 2), [], "d")
    assert r.is_complete is False
    assert r.structured_fields == frozenset({"name", "child", "tags", "desc"})
    assert r.failed_fields == frozenset()
    assert isinstance(r.errors, ClassValidationError)
    assert any(
        isinstance(e, ForbiddenExtraKeysError) for e in r.errors.exceptions
    )


def test_refine_fixes_failed_fields():
    c = Converter()
    r = c.partial_structure({"name": "n", "child": {"x": 1, "y": 2}}, Parent)
    assert not r.is_complete
    r2 = r.refine({"tags": [1], "desc": "d"})
    assert r2.is_complete is True
    assert r2.value == Parent("n", Child(1, 2), [1], "d")
    assert r2.failed_fields == frozenset()
    assert r2.errors is None


def test_refine_preserves_structured_fields():
    c = Converter()
    calls = []

    def hook(val, _):
        calls.append(val)
        return int(val)

    c.register_structure_hook(int, hook)
    r = c.partial_structure({"name": "n", "child": {"x": 1, "y": 2}}, Parent)
    calls.clear()
    # try to change name (structured) - should be ignored. The structured
    # fields name and child must not be re-structured during refine.
    r2 = r.refine({"name": "ignored", "tags": [1]})
    assert r2.value.name == "n"
    assert r2.value.child == Child(1, 2)
    # tags (previously failed) is structured now, so hook called once for it.
    assert calls == [1]
    assert "tags" in r2.structured_fields


def test_refine_recovers_value_none():
    c = Converter()
    r = c.partial_structure({}, Parent)
    assert r.value is None
    r2 = r.refine({"name": "n", "child": {"x": 1, "y": 2}})
    assert r2.value is not None
    assert r2.value.name == "n"
    assert "child" in r2.structured_fields


def test_refine_nested():
    c = Converter()
    r = c.partial_structure({"name": "n", "child": {"x": 1}}, Parent)
    assert "child" in r.failed_fields
    r2 = r.refine({"child": {"x": 1, "y": 5}})
    assert r2.value.child == Child(1, 5)
    assert "child" in r2.structured_fields


def test_detailed_validation_notes():
    c = Converter(detailed_validation=True)
    r = c.partial_structure({"name": "n", "child": {"x": 1}}, Parent)
    exc = r.error_map["child"]
    assert isinstance(exc, ClassValidationError)
    notes = exc.exceptions[0].__notes__
    assert any("child" not in (n or "") for n in notes)  # nested notes exist


def test_non_detailed_no_notes():
    c = Converter(detailed_validation=False)
    r = c.partial_structure({"name": "n", "child": {"x": "bad"}}, Parent)
    exc = r.error_map["child"]
    assert not isinstance(exc, ClassValidationError)
    assert getattr(exc, "__notes__", None) is None


def test_top_level_partial_structure():
    from cattrs import global_converter

    r = global_converter.partial_structure({"a": 1}, TD)
    assert r.value == {"a": 1}


def test_use_alias():
    @define
    class Alias:
        a: int = field(alias="A")
        b: str = field(alias="B", default="x")

    c = Converter(use_alias=True)
    r = c.partial_structure({"A": 1}, Alias)
    assert r.value == Alias(1, "x")
    assert r.structured_fields == frozenset({"a"})
    assert r.failed_fields == frozenset({"b"})
    r2 = r.refine({"B": "y"})
    assert r2.value == Alias(1, "y")
    assert r2.is_complete is True


def test_optional_nested():
    @dataclass
    class P:
        child: Optional[ChildDC] = None

    c = Converter()
    r = c.partial_structure({"child": {"x": 1}}, P)
    assert r.value == P(ChildDC(1, 0))
    assert r.is_complete is False
    assert "child" in r.failed_fields

    r = c.partial_structure({"child": None}, P)
    assert r.value == P(None)
    assert r.is_complete is True
    assert "child" in r.structured_fields

    r = c.partial_structure({}, P)
    assert r.value == P(None)
    assert r.is_complete is False
    assert "child" in r.failed_fields


def test_plain_type():
    c = Converter()
    r = c.partial_structure("1", int)
    assert r.value == 1
    assert r.is_complete is True

    r = c.partial_structure("x", int)
    assert r.value is None
    assert r.is_complete is False
    assert isinstance(r.errors, ValueError)
