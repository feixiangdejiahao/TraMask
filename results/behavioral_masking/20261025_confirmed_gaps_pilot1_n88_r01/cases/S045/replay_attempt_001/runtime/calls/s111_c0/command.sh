cat > /tmp/test_json.py <<'PYEOF'
from langchain_core.runnables import RunnableLambda
r = RunnableLambda(lambda x: x+1).with_coalesce()
print(r.to_json())
print("get_graph nodes:", r.get_graph().nodes)
PYEOF
cd /app/libs/core && timeout 15 python /tmp/test_json.py