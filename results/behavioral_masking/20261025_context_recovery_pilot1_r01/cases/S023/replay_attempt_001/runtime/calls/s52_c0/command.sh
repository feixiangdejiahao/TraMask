cd /app && python - <<'EOF'
from cattrs.gen.typeddicts import _adapted_fields, _required_keys
from typing import TypedDict

class TDOpt(TypedDict, total=False):
    a: int
    b: str

fs = _adapted_fields(TDOpt)
for a in fs:
    print(a.name, "alias=", repr(a.alias), "init=", a.init, "type=", a.type)
print("required", _required_keys(TDOpt))
EOF