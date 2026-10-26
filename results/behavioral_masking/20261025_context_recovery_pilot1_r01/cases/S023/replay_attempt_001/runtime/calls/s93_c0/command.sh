cd /app && python - <<'EOF'
from attrs import define
from cattrs import Converter
c = Converter(forbid_extra_keys=True)
@define
class A:
    x: int
res = c.partial_structure({"x": 1, "extra": 2}, A)
print(res.value, res.is_complete, res.structured_fields, res.failed_fields, res.errors)
EOF