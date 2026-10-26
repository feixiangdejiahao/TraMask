cat > /tmp/test_join_after_clear.py <<'PYEOF'
import asyncio
from langchain_core.runnables.coalesce import InMemoryCoalesceBackend

b = InMemoryCoalesceBackend()
b.register("k")
b.clear()
try:
    b.join("k")
except asyncio.CancelledError:
    print("sync join after clear -> CancelledError OK")
except Exception as e:
    print("sync join after clear ->", type(e), e)

async def main():
    await b.aregister("k2")
    b.clear()
    try:
        await b.ajoin("k2")
    except asyncio.CancelledError:
        print("async join after clear -> CancelledError OK")
    except Exception as e:
        print("async join after clear ->", type(e), e)
asyncio.run(main())
PYEOF
cd /app/libs/core && timeout 15 python /tmp/test_join_after_clear.py