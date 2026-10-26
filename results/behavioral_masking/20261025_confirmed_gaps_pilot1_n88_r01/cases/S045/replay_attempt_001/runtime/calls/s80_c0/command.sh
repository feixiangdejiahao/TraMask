cat > /tmp/mini2.py <<'PYEOF'
import threading
from concurrent.futures import ThreadPoolExecutor
from langchain_core.runnables.coalesce import InMemoryCoalesceBackend

backend = InMemoryCoalesceBackend()

def make_run_one(backend):
    barrier = threading.Barrier(5)
    def run_one(i, input_):
        barrier.wait(timeout=5)
        return backend.register(input_)
    return run_one

run_one = make_run_one(backend)
with ThreadPoolExecutor() as ex:
    results = list(ex.map(run_one, range(5), [1,2,1,1,2]))
print(results)
print(backend.stats)
PYEOF
cd /app/libs/core && timeout 15 python /tmp/mini2.py