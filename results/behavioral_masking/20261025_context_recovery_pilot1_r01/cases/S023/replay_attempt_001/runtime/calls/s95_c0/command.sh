cd /app && python - <<'EOF'
from dataclasses import dataclass, field
from cattrs import Converter
@dataclass
class A:
    x: int
    items: list = field(default_factory=list)
c = Converter()
r = c.partial_structure({"x": 1}, A)
print(r.value, r.failed_fields)
EOF