cd /app && cat > /tmp/dbg.py <<'EOF'
from attrs import define, field
from cattrs import Converter
from cattrs.partial import partial_structure, _partial_structure_attrs

@define
class Inner:
    x: int
    y: str = "hello"

@define
class Outer:
    inner: Inner
    z: int = 5
    items: list[int] = field(factory=list)

c = Converter()

# nested directly
sub = c.partial_structure({"x": 1}, Inner)
print("sub:", sub)
print("sub.value:", sub.value, type(sub.value))
print("sub.structured:", sub.structured_fields, "failed:", sub.failed_fields, "complete:", sub.is_complete)

# call inner helper
from cattrs._compat import adapted_fields
attrs = adapted_fields(Outer)
for a in attrs:
    print(a.name, "alias=", a.alias, "init=", a.init, "default=", a.default, "type=", a.type)
EOF
python /tmp/dbg.py