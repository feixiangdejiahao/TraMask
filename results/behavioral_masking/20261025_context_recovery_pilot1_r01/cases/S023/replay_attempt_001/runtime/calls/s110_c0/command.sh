cd /app && python - <<'EOF'
import cattrs, cattr
print(cattrs.partial_structure, cattr.partial_structure)
print(cattrs.PartialResult, cattr.PartialResult)
from cattrs.partial import partial_structure, PartialResult
from cattr.partial import partial_structure as ps, PartialResult as PR
print(partial_structure, ps, PartialResult, PR)
print("OK")
EOF