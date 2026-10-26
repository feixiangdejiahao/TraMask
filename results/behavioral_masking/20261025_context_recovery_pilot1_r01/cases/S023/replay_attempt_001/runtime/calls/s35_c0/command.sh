cd /app && cat > /tmp/test_spec.py <<'EOF'
from __future__ import annotations
from attrs import define, field
from dataclasses import dataclass, field as dc_field
from typing import List, Dict, TypedDict, Optional
from cattrs import Converter, partial_structure, PartialResult
import cattrs, cattr

print("exports:", hasattr(cattrs, "partial_structure"), hasattr(cattr, "partial_structure"), hasattr(cattrs, "PartialResult"), hasattr(cattr, "PartialResult"))

c = Converter()

# --- Complete object ---
@define
class Complete:
    a: int
    b: str = "x"
r = c.partial_structure({"a": 1, "b": "y"}, Complete)
print("complete:", r.value, r.is_complete, r.structured_fields, r.failed_fields, r.errors, r.error_map)
assert r.is_complete and r.value == Complete(1, "y")
assert r.structured_fields == frozenset({"a","b"}) and r.failed_fields == frozenset()

# --- absent with default -> failed, value still built ---
@define
class Def:
    a: int
    b: str = "d"
r = c.partial_structure({"a": 1}, Def)
print("def:", r.value, r.structured_fields, r.failed_fields)
assert r.value == Def(1) and not r.is_complete
assert r.failed_fields == frozenset({"b"}) and r.structured_fields == frozenset({"a"})
assert r.errors is not None and "b" in r.error_map

# --- required missing -> None ---
@define
class Req:
    a: int
    b: str
r = c.partial_structure({"a": 1}, Req)
print("req:", r.value, r.failed_fields)
assert r.value is None and r.failed_fields == frozenset({"b"})

# --- nested partial ---
@define
class Inner:
    x: int
    y: str = "d"
@define
class Outer:
    inner: Inner
    z: int
r = c.partial_structure({"inner": {"x": 1}, "z": 5}, Outer)
print("nested:", r.value, r.structured_fields, r.failed_fields)
assert r.value == Outer(Inner(x=1), 5)
assert r.structured_fields == frozenset({"z"})
assert r.failed_fields == frozenset({"inner"})
assert r.error_map["inner"] is not None

# --- nested no value -> normal failure -> required missing -> None ---
@define
class InnerReq:
    x: int
    y: int
@define
class OuterReq:
    inner: InnerReq
    z: int
r = c.partial_structure({"inner": {"x": 1}, "z": 5}, OuterReq)
print("nested none:", r.value, r.failed_fields)
assert r.value is None and r.failed_fields == frozenset({"inner"})

# --- collection atomic ---
@define
class Col:
    items: List[int]
    m: Dict[str, int]
r = c.partial_structure({"items": [1, "bad"], "m": {"a": 1}}, Col)
print("col:", r.value, r.structured_fields, r.failed_fields, r.error_map)
assert r.value is None
assert r.structured_fields == frozenset({"m"})
assert r.failed_fields == frozenset({"items"})
assert isinstance(r.error_map["items"], Exception)

# --- init=False excluded ---
@define
class InitFalse:
    a: int
    b: int = field(init=False, default=10)
r = c.partial_structure({"a": 1}, InitFalse)
print("initfalse:", r.value, r.structured_fields, r.failed_fields)
assert r.value == InitFalse(1)  # b=10 set by attrs
assert r.structured_fields == frozenset({"a"})
assert r.failed_fields == frozenset()
assert r.is_complete

# --- dataclass ---
@dataclass
class D:
    a: int
    b: str = "hi"
r = c.partial_structure({"a": 2}, D)
print("dataclass:", r.value, r.structured_fields, r.failed_fields)
assert r.value == D(2) and r.failed_fields == frozenset({"b"})

# --- typeddict ---
class TD(TypedDict):
    a: int
    b: str

r = c.partial_structure({"a": 1}, TD)
print("typeddict:", r.value, r.structured_fields, r.failed_fields)
assert r.value is None  # b required missing
assert r.structured_fields == frozenset({"a"})
assert r.failed_fields == frozenset({"b"})

class TDOpt(TypedDict, total=False):
    a: int
    b: str

r = c.partial_structure({}, TDOpt)
print("typeddict opt:", r.value, r.structured_fields, r.failed_fields)
assert r.value == {} and r.failed_fields == frozenset({"a","b"})

# --- forbid extra keys ---
cf = Converter(forbid_extra_keys=True)
r = cf.partial_structure({"a": 1, "extra": 2}, Complete)
print("forbid:", r.value, r.is_complete, r.structured_fields, r.failed_fields, r.errors)
assert r.value == Complete(1, "x") and not r.is_complete
assert r.failed_fields == frozenset({"b"})
assert r.errors is not None

# --- detailed_validation false ---
cn = Converter(detailed_validation=False)
r = cn.partial_structure({"a": "bad"}, Complete)
print("nodetail:", r.errors, r.error_map)
assert r.errors is not None

# --- refine preserves structured ---
r = c.partial_structure({"a": 1}, Complete)
r2 = r.refine({"a": 999, "b": "z"})
print("refine preserve:", r2.value)
assert r2.value == Complete(1, "z")
assert r2.is_complete

# --- refine nested ---
r = c.partial_structure({"inner": {"x": 1}, "z": 5}, Outer)
r2 = r.refine({"inner": {"y": "w"}})
print("refine nested:", r2.value, r2.is_complete)
assert r2.value == Outer(Inner(1, "w"), 5)
assert r2.is_complete

# --- top-level partial_structure ---
r = partial_structure({"a": 1}, Complete)
print("toplevel:", r.value)
assert isinstance(r, PartialResult)

print("ALL OK")
EOF
python /tmp/test_spec.py