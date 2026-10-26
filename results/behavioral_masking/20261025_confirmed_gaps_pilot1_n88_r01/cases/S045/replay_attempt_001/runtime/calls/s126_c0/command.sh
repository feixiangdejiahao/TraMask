cat > /tmp/test_atransform.py <<'PYEOF'
import asyncio
from langchain_core.runnables import RunnableLambda

async def f(x):
    return x + 1

r = RunnableLambda(f).with_coalesce()

async def inputs():
    yield 5
    yield 6

async def main():
    out = []
    async for chunk in r.atransform(inputs()):
        out.append(chunk)
    return out

print(asyncio.run(main()))
PYEOF
cd /app/libs/core && timeout 15 python /tmp/test_atransform.py