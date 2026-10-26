cat > /tmp/test_dict_tricky.py <<'PYEOF'
from langchain_core.runnables.coalesce import _canonical_key

d1 = {1: "a", "x": [3, 2], (1, 2): {"b": 2, "a": 1}}
d2 = {"x": [2, 3], (1, 2): {"a": 1, "b": 2}, 1: "a"}
k1 = _canonical_key(d1)
k2 = _canonical_key(d2)
print(k1)
print(k2)
print("equal:", k1 == k2)
PYEOF
cd /app/libs/core && timeout 15 python /tmp/test_dict_tricky.py