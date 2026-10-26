cat > /tmp/test_binding_attrs.py <<'PYEOF'
import time
from langchain_core.runnables import RunnableLambda, InMemoryCoalesceBackend

def f(x, extra=0):
    time.sleep(0.1)
    return x + extra

r = RunnableLambda(f).with_coalesce()
b = r.bind(extra=10)
print("coalesce_info via binding __getattr__:", b.coalesce_info())
c = b.with_config({"tags": ["x"]})
print("coalesce_info via config binding:", c.coalesce_info())

# test shared backend through binding
backend = InMemoryCoalesceBackend()
r1 = RunnableLambda(f).with_coalesce(backend=backend)
r2 = RunnableLambda(f).with_coalesce(backend=backend).bind(extra=1)
import threading
res = []
t1 = threading.Thread(target=lambda: res.append(r1.invoke(1)))
t2 = threading.Thread(target=lambda: res.append(r2.invoke(1)))
t1.start(); t2.start(); t1.join(); t2.join()
print("res", res)
print("stats", backend.stats)
PYEOF
cd /app/libs/core && timeout 20 python /tmp/test_binding_attrs.py