from dataclasses import dataclass

import pytest

from adaptix import DebugTrail, ExtraForbid, NameStyle, Retort, name_mapping
from adaptix._internal.morphing.load_error import ExtraFieldsLoadError, TypeLoadError
from adaptix._internal.struct_trail import get_trail


@dataclass
class AliasedModel:
    a: int = 0
    b: int = 0


def test_aliases_loading():
    retort = Retort(recipe=[name_mapping(aliases={"a": "x", "b": ["y", "z"]})])
    assert retort.load({"a": 1}, AliasedModel) == AliasedModel(a=1)
    assert retort.load({"x": 1}, AliasedModel) == AliasedModel(a=1)
    assert retort.load({"z": 2}, AliasedModel) == AliasedModel(b=2)


def test_aliases_multi_key_conflict():
    retort = Retort(
        recipe=[name_mapping(aliases={"a": "x"})],
    ).replace(debug_trail=DebugTrail.FIRST)
    with pytest.raises(ExtraFieldsLoadError):
        retort.load({"a": 1, "x": 2}, AliasedModel)


def test_aliases_recognized_by_extra_forbid():
    retort = Retort(recipe=[name_mapping(aliases={"a": "x"}, extra_in=ExtraForbid())])
    assert retort.load({"x": 1}, AliasedModel) == AliasedModel(a=1)
    with pytest.raises(Exception):
        retort.load({"x": 1, "unknown": 2}, AliasedModel)


def test_alias_style():
    @dataclass
    class User:
        user_name: str = ""

    retort = Retort(recipe=[name_mapping(alias_style=[NameStyle.CAMEL, NameStyle.UPPER_SNAKE])])
    assert retort.load({"userName": "alice"}, User) == User("alice")
    assert retort.load({"USER_NAME": "bob"}, User) == User("bob")
    assert retort.load({"user_name": "carol"}, User) == User("carol")


def test_aliases_ignored_under_as_list():
    @dataclass
    class RequiredModel:
        a: int
        b: int

    retort = Retort(recipe=[name_mapping(aliases={"a": "x"}, as_list=True)])
    assert retort.load([1, 2], RequiredModel) == RequiredModel(1, 2)


def test_explicit_alias_equal_to_primary_key_errors():
    with pytest.raises(ValueError):
        Retort(recipe=[name_mapping(aliases={"a": "a"})]).get_loader(AliasedModel)


def test_generated_alias_equal_to_primary_key_pruned():
    retort = Retort(recipe=[name_mapping(alias_style=NameStyle.LOWER)])
    assert retort.load({"a": 1}, AliasedModel) == AliasedModel(a=1)


def test_cross_field_alias_collision_errors():
    with pytest.raises(Exception):
        Retort(recipe=[name_mapping(aliases={"a": "b"})]).get_loader(AliasedModel)
    with pytest.raises(Exception):
        Retort(recipe=[name_mapping(aliases={"a": "x", "b": "x"})]).get_loader(AliasedModel)


def test_alias_trail_reflects_resolved_key():
    @dataclass
    class RequiredModel:
        a: int

    retort = Retort(
        recipe=[name_mapping(aliases={"a": "x"})],
    ).replace(debug_trail=DebugTrail.FIRST)
    with pytest.raises(TypeLoadError) as exc_info:
        retort.load({"x": "bad"}, RequiredModel)
    assert list(get_trail(exc_info.value)) == ["x"]


def test_aliases_overlay_merge_first_wins():
    retort = Retort(recipe=[
        name_mapping(aliases={"a": "low"}),
        name_mapping(aliases={"a": "high"}),
    ])
    assert retort.load({"low": 1}, AliasedModel) == AliasedModel(a=1)
    assert retort.load({"high": 1}, AliasedModel) == AliasedModel(a=0)
