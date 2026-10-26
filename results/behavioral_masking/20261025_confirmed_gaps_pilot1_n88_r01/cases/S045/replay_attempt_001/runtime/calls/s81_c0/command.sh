cat > /tmp/mini3.py <<'PYEOF'
import threading
from langchain_core.runnables.config import ContextThreadPoolExecutor
from langchain_core.runnables.coalesce import InMemoryCoalesceBackend

backend = InMemoryCoalesceBackend()
barrier = threading.Barrier(5)
def run_one(i, input_):
    barrier.wait(timeout=5)
    return backend.register(input_)

with ContextThreadPoolExecutor() as ex:
    results = list(ex.map(run_one, range(5), [1,2,1,1,2]))
print(results)
print(backend.stats)
PYEOF
cd /app/libs/core && timeout 15 python /tmp/mini3.py