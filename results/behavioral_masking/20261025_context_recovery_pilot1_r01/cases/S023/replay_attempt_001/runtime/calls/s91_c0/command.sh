cd /app && python - <<'EOF'
from typing import TypedDict
from cattrs import Converter
class TD(TypedDict):
    a: int
    b: str
c = Converter()
res = c.partial_structure({"a": 1}, TD)
print("initial:", res.value, res.structured_fields, res.failed_fields, res.is_complete)
res2 = res.refine({"b": "x"})
print("refined:", res2.value, res2.structured_fields, res2.failed_fields, res2.is_complete)
EOF