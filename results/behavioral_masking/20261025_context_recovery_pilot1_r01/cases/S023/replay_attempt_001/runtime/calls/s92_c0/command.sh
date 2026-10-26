cd /app && python - <<'EOF'
from cattr.partial import PartialResult, partial_structure
from cattrs.partial import PartialResult as PR2, partial_structure as ps2
from cattrs import PartialResult as PR3
print(PartialResult, PR2, PR3)
print(partial_structure is ps2)
EOF