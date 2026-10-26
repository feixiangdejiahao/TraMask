cat > /tmp/inspect_backend.py <<'PYEOF'
from langchain_core.runnables import RunnableLambda

r = RunnableLambda(lambda x: x+1).with_coalesce()
b = r.backend
print("type:", type(b))
print("mro:", [c.__name__ for c in type(b).__mro__])
print("is pydantic:", hasattr(b, "model_fields"))
print("dict:", b.__dict__ if hasattr(b, "__dict__") else None)
print("executions type:", type(b._executions))
# register directly
print("register 1:", b.register(1))
print("execs after direct:", list(b._executions.keys()), [type(k).__name__ for k in b._executions.keys()])
PYEOF
cd /app/libs/core && timeout 15 python /tmp/inspect_backend.py