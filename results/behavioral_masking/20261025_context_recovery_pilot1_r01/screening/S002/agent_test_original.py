from dataclasses import dataclass

import pytest

from adaptix import DebugTrail, ExtraCollect, ExtraForbid, NameStyle, Retort, name_mapping
from adaptix._internal.definitions import Direction
from adaptix._internal.morphing.json_schema.request_cls import JSONSchemaContext
from adaptix._internal.morphing.json_schema.schema_model import JSONSchemaDialect, JSONSchemaType
from adaptix.load_error import ExtraFieldsLoadError
from adaptix.struct_trail import get_trail


@dataclass
class Foo:
    my_field: int = 0
    other: int = 0


def test_aliases_load_from_primary_key_first_then_in_order():
    retort = Retort(
        recipe=[
            name_mapping(aliases={"my_field": ["x", "y"]}),
        ],
    )
    assert retort.load({"my_field": 1, "other": 0}, Foo) == Foo(my_field=1, other=0)
    assert retort.load({"x": 1, "other": 0}, Foo) == Foo(my_field=1, other=0)
    assert retort.load({"y": 1, "other": 0}, Foo) == Foo(my_field=1, other=0)


def test_aliases_are_load_only():
    retort = Retort(
        recipe=[
            name_mapping(aliases={"my_field": ["x", "y"]}),
        ],
    )
    assert retort.dump(Foo(my_field=1, other=2)) == {"my_field": 1, "other": 2}


def test_alias_as_single_string():
    retort = Retort(
        recipe=[
            name_mapping(aliases={"my_field": "x"}),
        ],
    )
    assert retort.load({"x": 1, "other": 0}, Foo) == Foo(my_field=1, other=0)


def test_aliases_are_literal_unaffected_by_name_style():
    retort = Retort(
        recipe=[
            name_mapping(
                aliases={"my_field": "snake_case"},
                name_style=NameStyle.CAMEL,
            ),
        ],
    )
    assert retort.load({"snake_case": 1, "other": 0}, Foo) == Foo(my_field=1, other=0)
    # primary key is still converted by name_style
    assert retort.load({"myField": 1, "other": 0}, Foo) == Foo(my_field=1, other=0)


def test_alias_conflict_raises_extra_fields_load_error():
    retort = Retort(
        recipe=[
            name_mapping(aliases={"my_field": ["x", "y"]}),
        ],
        debug_trail=DebugTrail.DISABLE,
    )
    with pytest.raises(ExtraFieldsLoadError) as exc_info:
        retort.load({"my_field": 1, "x": 2, "other": 0}, Foo)
    assert exc_info.value.fields == {"my_field", "x"}

    with pytest.raises(ExtraFieldsLoadError) as exc_info:
        retort.load({"x": 1, "y": 2, "other": 0}, Foo)
    assert exc_info.value.fields == {"x", "y"}


def test_alias_style_generates_aliases():
    retort = Retort(
        recipe=[
            name_mapping(alias_style=[NameStyle.CAMEL, NameStyle.PASCAL]),
        ],
    )
    assert retort.load({"myField": 1, "other": 0}, Foo) == Foo(my_field=1, other=0)
    assert retort.load({"MyField": 1, "Other": 0}, Foo) == Foo(my_field=1, other=0)


def test_alias_style_as_single_value():
    retort = Retort(
        recipe=[
            name_mapping(alias_style=NameStyle.CAMEL),
        ],
    )
    assert retort.load({"myField": 1, "other": 0}, Foo) == Foo(my_field=1, other=0)


def test_explicit_aliases_take_precedence_over_generated():
    retort = Retort(
        recipe=[
            name_mapping(
                aliases={"my_field": "custom"},
                alias_style=NameStyle.CAMEL,
            ),
        ],
    )
    assert retort.load({"custom": 1, "other": 0}, Foo) == Foo(my_field=1, other=0)
    assert retort.load({"myField": 1, "other": 0}, Foo) == Foo(my_field=1, other=0)


def test_alias_style_ignored_under_as_list():
    @dataclass
    class Lst:
        my_field: int
        other: int

    retort = Retort(
        recipe=[
            name_mapping(
                aliases={"my_field": "x"},
                alias_style=NameStyle.CAMEL,
                as_list=True,
            ),
        ],
    )
    assert retort.load([1, 2], Lst) == Lst(my_field=1, other=2)


def test_explicit_alias_equal_to_own_primary_key_raises():
    with pytest.raises(ValueError, match="equals its own primary key"):
        Retort(recipe=[name_mapping(aliases={"my_field": "my_field"})]).get_loader(Foo)


def test_generated_alias_equal_to_own_primary_key_is_pruned():
    retort = Retort(
        recipe=[
            name_mapping(alias_style=NameStyle.CAMEL),
        ],
    )
    # CAMEL of "other" is "other", so it must be pruned and not break anything
    assert retort.load({"myField": 1, "other": 0}, Foo) == Foo(my_field=1, other=0)


def test_generated_alias_equal_to_own_primary_key_allows_fallback_to_next_style():
    retort = Retort(
        recipe=[
            name_mapping(alias_style=[NameStyle.LOWER_SNAKE, NameStyle.CAMEL]),
        ],
    )
    # LOWER_SNAKE produces "my_field" (pruned), CAMEL produces "myField"
    assert retort.load({"myField": 1, "other": 0}, Foo) == Foo(my_field=1, other=0)


def test_alias_collision_with_other_primary_key_raises():
    with pytest.raises(ValueError, match="collides"):
        Retort(recipe=[name_mapping(aliases={"my_field": "other"})]).get_loader(Foo)


def test_alias_collision_with_other_alias_raises():
    with pytest.raises(ValueError, match="collides"):
        Retort(recipe=[name_mapping(aliases={"my_field": "x", "other": "x"})]).get_loader(Foo)


def test_alias_collision_with_branch_key_raises():
    @dataclass
    class Nested:
        a: int = 0
        b: int = 0

    with pytest.raises(ValueError, match="collides"):
        Retort(
            recipe=[
                name_mapping(
                    aliases={"a": "x"},
                    map={"b": ("x", "y")},
                ),
            ],
        ).get_loader(Nested)


def test_aliases_recognized_by_extra_forbid():
    retort = Retort(
        recipe=[
            name_mapping(
                aliases={"my_field": "x"},
                extra_in=ExtraForbid(),
            ),
        ],
        debug_trail=DebugTrail.DISABLE,
    )
    assert retort.load({"x": 1, "other": 0}, Foo) == Foo(my_field=1, other=0)

    with pytest.raises(ExtraFieldsLoadError):
        retort.load({"x": 1, "other": 0, "unknown": 2}, Foo)


def test_aliases_recognized_and_not_collected_by_extra_collect():
    @dataclass
    class Collecting:
        my_field: int = 0
        other: int = 0
        extra: dict = None  # type: ignore[assignment]

    retort = Retort(
        recipe=[
            name_mapping(
                aliases={"my_field": "x"},
                extra_in="extra",
            ),
        ],
    )
    result = retort.load({"x": 1, "other": 0, "unknown": 2}, Collecting)
    assert result.my_field == 1
    assert result.extra == {"unknown": 2}


def test_alias_overlay_merge_first_wins_per_field():
    retort = Retort(
        recipe=[
            name_mapping(aliases={"my_field": "first", "other": "outer"}),
            name_mapping(aliases={"my_field": "second"}),
        ],
    )
    assert retort.load({"first": 1, "outer": 0}, Foo) == Foo(my_field=1, other=0)
    assert retort.load({"second": 1, "outer": 0}, Foo) == Foo(my_field=0, other=0)


def test_alias_style_overlay_merge():
    retort = Retort(
        recipe=[
            name_mapping(alias_style=NameStyle.CAMEL),
            name_mapping(alias_style=NameStyle.PASCAL),
        ],
    )
    assert retort.load({"myField": 1, "other": 0}, Foo) == Foo(my_field=1, other=0)
    assert retort.load({"MyField": 1, "Other": 0}, Foo) == Foo(my_field=1, other=0)


def test_alias_trail_reflects_actual_resolved_key():
    retort = Retort(
        recipe=[
            name_mapping(aliases={"my_field": "x"}),
        ],
        debug_trail=DebugTrail.ALL,
    )
    with pytest.raises(Exception) as exc_info:
        retort.load({"x": "not-an-int", "other": 0}, Foo)
    errors = exc_info.value.exceptions
    assert len(errors) == 1
    assert list(get_trail(errors[0])) == ["x"]


def test_nested_alias_loading_and_trail():
    @dataclass
    class Nested:
        a: int = 0

    retort = Retort(
        recipe=[
            name_mapping(
                map={"a": ("x", "y")},
                aliases={"a": "z"},
            ),
        ],
        debug_trail=DebugTrail.ALL,
    )
    assert retort.load({"x": {"y": 1}}, Nested) == Nested(a=1)
    assert retort.load({"x": {"z": 1}}, Nested) == Nested(a=1)

    with pytest.raises(Exception) as exc_info:
        retort.load({"x": {"z": "bad"}}, Nested)
    assert list(get_trail(exc_info.value.exceptions[0])) == ["x", "z"]


def test_alias_input_json_schema_exposes_aliases_as_properties():
    retort = Retort(
        recipe=[
            name_mapping(
                aliases={"my_field": ["x", "y"]},
                alias_style=NameStyle.CAMEL,
            ),
        ],
    )
    schema = retort.make_json_schema(
        Foo,
        JSONSchemaContext(
            dialect=JSONSchemaDialect.DRAFT_2020_12,
            direction=Direction.INPUT,
        ),
    )
    inner_schema = schema.ref.json_schema
    assert inner_schema.type == JSONSchemaType.OBJECT
    assert set(inner_schema.properties.keys()) == {"my_field", "other", "x", "y", "myField"}
    assert inner_schema.properties["x"].type == JSONSchemaType.INTEGER
    assert inner_schema.properties["myField"].type == JSONSchemaType.INTEGER
    assert "x" not in inner_schema.required
    assert "my_field" not in inner_schema.required


def test_aliases_reject_non_string_keys():
    with pytest.raises(ValueError, match="valid field_id"):
        name_mapping(aliases={1: "x"})


def test_aliases_reject_non_string_values():
    with pytest.raises(ValueError, match="must be strings"):
        name_mapping(aliases={"my_field": [1]})


def test_alias_style_reject_invalid_values():
    with pytest.raises(ValueError, match="NameStyle"):
        name_mapping(alias_style="not-a-style")
