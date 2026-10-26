cd /app && python - <<'EOF'
from attrs import define
from cattrs import Converter
@define
class Inner:
    x: int
    y: int
@define
class Outer:
    inner: Inner
    z: int = 5
c = Converter()
res = c.partial_structure({"inner": {"x": 3}}, Outer)
print("initial:", res.value, res.failed_fields)
res2 = res.refine({"inner": {"y": 4}})
print("refined:", res2.value, res2.failed_fields, res2.is_complete, res2.structured_fields)
EOF