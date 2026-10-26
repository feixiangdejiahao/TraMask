cat > /tmp/backend_test.py <<'PYEOF'
import threading, time
from langchain_core.runnables.coalesce import InMemoryCoalesceBackend

b = InMemoryCoalesceBackend()
results = {}
barrier = threading.Barrier(5)
def worker(i):
    barrier.wait()
    r = b.register(i % 2)
    results[i] = r

threads = [threading.Thread(target=worker, args=(i,)) for i in range(5)]
for t in threads: t.start()
for t in threads: t.join()
print("results:", results)
print("stats:", b.stats)
print("executions:", b._executions)
PYEOF
cd /app/libs/core && timeout 15 python /tmp/backend_test.py