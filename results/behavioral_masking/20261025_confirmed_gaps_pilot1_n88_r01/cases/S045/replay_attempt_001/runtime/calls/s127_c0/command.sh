cat > /tmp/test_bac_error.py <<'PYEOF'
import time
from langchain_core.runnables import RunnableLambda

calls = []
def f(x):
    time.sleep(0.05)
    calls.append(x)
    if x == 3:
        raise ValueError("bad")
    return x

r = RunnableLambda(f).with_coalesce()
results = list(r.batch_as_completed([1, 1, 3, 3], return_exceptions=True))
print(results)
idxs = [i for i, _ in results]
# 0 and 1 consecutive, 2 and 3 consecutive
assert abs(idxs.index(0) - idxs.index(1)) == 1
assert abs(idxs.index(2) - idxs.index(3)) == 1
print("OK")
PYEOF
cd /app/libs/core && timeout 20 python /tmp/test_bac_error.py