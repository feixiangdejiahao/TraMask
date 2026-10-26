cd /app && cat > /tmp/edge.py <<'EOF'
from __future__ import annotations
from attrs import define, field
from typing import List, Dict, Optional, TypedDict, Annotated
from cattrs import BaseConverter, Converter
from cattrs import override

# BaseConverter
@define
class A:
    x: int
    y: str = "d"
bc = BaseConverter()
r = bc.partial_structure({"x": 1}, A)
print("baseconverter:", r.value, r.structured_fields, r.failed_fields, r.is_complete)
assert r.value == A(1) and r.failed_fields == frozenset({"y"})

# alias use_alias
@define
class Alias:
    x: int
    y: int = field(alias="yy")
ca = Converter(use_alias=True)
r = ca.partial_structure({"x": 1, "yy": 2}, Alias)
print("alias:", r.value, r.structured_fields, r.failed_fields, r.is_complete)
assert r.value == Alias(1, 2)
assert r.structured_fields == frozenset({"x","y"})

# alias without use_alias (input by name, kwargs by alias)
cn = Converter(use_alias=False)
r = cn.partial_structure({"x": 1, "y": 2}, Alias)
print("noalias:", r.value, r.structured_fields)
assert r.value == Alias(1, 2)

# optional nested - atomic
@define
class In:
    x: int
    y: str = "d"
@define
class Opt:
    inner: Optional[In] = None
r = c = Converter()
r = c.partial_structure({"inner": {"x": 1}}, Opt)
print("optional nested:", r.value, r.structured_fields, r.failed_fields)
# Optional[In] is not partial-recursive -> structured atomically -> complete -> structured
assert r.value == Opt(In(1)) and r.is_complete

# typeddict nested in attrs
class TD(TypedDict):
    a: int
    b: str
@define
class WithTD:
    td: TD
    z: str = "zz"
r = c.partial_structure({"td": {"a": 1}}, WithTD)
print("td nested:", r.value, r.structured_fields, r.failed_fields)
# TD has b required missing -> sub value None -> normal failure -> default z, td required no default -> None
assert r.value is None
assert r.failed_fields == frozenset({"td"})

class TDOpt(TypedDict, total=False):
    a: int
    b: str
@define
class WithTDOpt:
    td: TDOpt
    z: str = "zz"
r = c.partial_structure({"td": {"a": 1}}, WithTDOpt)
print("tdopt nested:", r.value, r.structured_fields, r.failed_fields)
assert r.value == WithTDOpt({"a": 1}, "zz")
assert r.failed_fields == frozenset({"td"})

# attrs nested in typeddict
@define
class In2:
    x: int
    y: str = "d"
class TDA(TypedDict):
    inner: In2
    z: int
r = c.partial_structure({"inner": {"x": 1}, "z": 5}, TDA)
print("attrs in td:", r.value, r.structured_fields, r.failed_fields)
assert r.value == {"inner": In2(1), "z": 5}
assert r.structured_fields == frozenset({"z"})
assert r.failed_fields == frozenset({"inner"})

# list of attrs atomic
@define
class WithList:
    items: List[In]
r = c.partial_structure({"items": [{"x": 1}]}, WithList)
print("list attrs:", r.value, r.structured_fields, r.failed_fields, r.is_complete)
assert r.is_complete and r.value == WithList([In(1)])

r = c.partial_structure({"items": [{"x": 1}, {"bad": 2}]}, WithList)
print("list attrs fail:", r.value, r.failed_fields)
assert r.value is None and r.failed_fields == frozenset({"items"})

# init=False with no default -> excluded, value constructible
@define
class IF:
    x: int
    computed: int = field(init=False)
    def __attrs_post_init__(self):
        self.computed = self.x * 2
r = c.partial_structure({"x": 3}, IF)
print("initfalse nodefault:", r.value, r.structured_fields, r.failed_fields, r.is_complete)
assert r.value == IF(3) and r.is_complete and r.failed_fields == frozenset()

# annotated
@define
class Ann:
    x: Annotated[int, "meta"]
    y: str = "d"
r = c.partial_structure({"x": 5}, Ann)
print("annotated:", r.value, r.failed_fields)
assert r.value == Ann(5)

print("EDGE OK")
EOF
python /tmp/edge.py