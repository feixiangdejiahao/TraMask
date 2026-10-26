cd /app/libs/core && python -c "
from langchain_core.runnables import CoalesceBackend, CoalesceStats, InMemoryCoalesceBackend, Runnable, RunnableLambda
print(CoalesceBackend, CoalesceStats, InMemoryCoalesceBackend)
r = RunnableLambda(lambda x: x + 1)
c = r.with_coalesce()
print(type(c), c.coalesce_info())
print(c.invoke(1))
"