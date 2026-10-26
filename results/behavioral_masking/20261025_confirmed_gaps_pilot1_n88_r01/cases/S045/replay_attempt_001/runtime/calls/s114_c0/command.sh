cat > /tmp/test_dict_order2.py <<'PYEOF'
from langchain_core.runnables.coalesce import _canonical_key

d1 = {"a": 1, "b": 2, "c": {"x": 1, "y": 2}}
d2 = {"c": {"y": 2, "x": 1}, "b": 2, "a": 1}
print(_canonical_key(d1))
print(_canonical_key(d2))
print("equal:", _canonical_key(d1) == _canonical_key(d2))
PYEOF
cd /app/libs/core && timeout 15 python /tmp/test_dict_order2.py