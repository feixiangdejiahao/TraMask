cd /app && cat > /tmp/dbg2.py <<'EOF'
import cattrs.partial as p
from attrs import define, field
from cattrs import Converter

orig = p._partial_structure_fields

def traced(converter, obj, cl, attrs, *, required):
    print("TRACE", cl.__name__, "obj=", obj)
    for a in attrs:
        print("  field", a.name, "in obj?", a.name in obj, "type", a.type, "has?", p._is_partial_type(a.type), "required?", required(a))
    return orig(converter, obj, cl, attrs, required=required)

p._partial_structure_fields = traced

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
r = c.partial_structure({"inner": {"x": 1}}, Outer)
print("RESULT:", r.value, r.structured_fields, r.failed_fields, r.is_complete)
print("errors:", r.errors, r.errors.exceptions if r.errors else None)
print("errormap:", r.error_map)
EOF
python /tmp/dbg2.py