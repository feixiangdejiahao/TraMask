cat > /tmp/debug2.py <<'PYEOF'
import time
from langchain_core.runnables import RunnableLambda

calls = []
def f(x):
    time.sleep(0.2)
    calls.append(x)
    return x + 1

r = RunnableLambda(f).with_coalesce()
out = r.batch([1, 2, 1, 1, 2])
print("out:", out)
print("calls:", calls)
print("stats:", r.coalesce_info())
PYEOF
cd /app/libs/core && timeout 15 python /tmp/debug2.py