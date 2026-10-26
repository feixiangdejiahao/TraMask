cd /app && cat > src/cattr/partial.py <<'PYEOF'
from cattrs.partial import PartialResult, partial_structure

__all__ = ["PartialResult", "partial_structure"]
PYEOF
python - <<'EOF'
path = 'src/cattr/__init__.py'
src = open(path).read()
src = src.replace("from .partial import PartialResult, partial_structure\n", "from .partial import PartialResult, partial_structure\n")
open(path, 'w').write(src)
EOF
cd /app && python /tmp/test_spec.py