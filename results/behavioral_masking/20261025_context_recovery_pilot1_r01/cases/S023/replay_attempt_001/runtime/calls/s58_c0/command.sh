cd /app && cat > /tmp/errcheck.py <<'EOF'
from attrs import define
from cattrs import Converter
from cattrs.errors import ClassValidationError

@define
class Inner:
    x: int
    y: str = "d"

@define
class Outer:
    inner: Inner
    z: int = 5

c = Converter()
r = c.partial_structure({"inner": {"x": 1}}, Outer)
print("errors type:", type(r.errors), isinstance(r.errors, ClassValidationError))
print("error_map keys:", r.error_map.keys())
for k, e in r.error_map.items():
    print(" ", k, type(e).__name__, str(e)[:80])
    print("    notes:", getattr(e, "__notes__", None))
EOF
python /tmp/errcheck.py