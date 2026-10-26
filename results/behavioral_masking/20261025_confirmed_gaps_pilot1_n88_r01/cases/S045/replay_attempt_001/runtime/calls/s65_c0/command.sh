cat > /tmp/mini.py <<'PYEOF'
import asyncio
from langchain_core.runnables import RunnableLambda

async def main():
    async def gen(x):
        print("gen start", flush=True)
        yield "a"
        print("gen after a", flush=True)
        await asyncio.sleep(0.05)
        yield "b"
        yield "c"
        print("gen done", flush=True)

    r = RunnableLambda(gen).with_coalesce()
    it1 = r.astream(1)
    it2 = r.astream(1)
    print("created", flush=True)
    c1 = await anext(it1)
    print("c1", c1, flush=True)
    await asyncio.sleep(0.1)
    print("before c2", flush=True)
    c2 = await anext(it2)
    print("c2", c2, flush=True)
    print("rest1...", flush=True)
    rest1 = [c async for c in it1]
    print("rest1", rest1, flush=True)
    rest2 = [c async for c in it2]
    print("rest2", rest2, flush=True)

asyncio.run(main())
PYEOF
cd /app/libs/core && timeout 15 python /tmp/mini.py; echo "exit: $?"