cat > /tmp/test_more_edge.py <<'PYEOF'
import asyncio, time, threading
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.runnables import RunnableLambda

class H(BaseCallbackHandler):
    def __init__(self):
        self.starts = 0
        self.ends = 0
        self.errors = 0
    def on_chain_start(self, *a, **k): self.starts += 1
    def on_chain_end(self, *a, **k): self.ends += 1
    def on_chain_error(self, *a, **k): self.errors += 1

# stream joiner callbacks
async def test_stream_callbacks():
    async def gen(x):
        yield "a"
        await asyncio.sleep(0.05)
        yield "b"
    r = RunnableLambda(gen).with_coalesce()
    h1, h2 = H(), H()
    async def main():
        it1 = r.astream(1, {"callbacks": [h1]})
        it2 = r.astream(1, {"callbacks": [h2]})
        first = await anext(it1)
        await asyncio.sleep(0.05)
        t = asyncio.create_task(anext(it2))
        rest1 = [c async for c in it1]
        second = await t
        rest2 = [c async for c in it2]
        return [first]+rest1, [second]+rest2
    r1, r2 = asyncio.run(main())
    print("stream callbacks:", h1.starts, h1.ends, h2.starts, h2.ends, r1, r2)
    assert h2.starts == 1 and h2.ends == 1

# abatch with max_concurrency=1 and duplicates
def test_abatch_max_concurrency():
    calls = []
    async def f(x):
        await asyncio.sleep(0.05)
        calls.append(x)
        return x
    r = RunnableLambda(f).with_coalesce()
    async def main():
        return await r.abatch([1, 1, 2], {"max_concurrency": 1})
    out = asyncio.run(main())
    print("abatch max_concurrency:", out, calls)
    assert out == [1, 1, 2] and len(calls) == 2

# abatch_as_completed max_concurrency
def test_abac_max_concurrency():
    calls = []
    async def f(x):
        await asyncio.sleep(0.05)
        calls.append(x)
        return x
    r = RunnableLambda(f).with_coalesce()
    async def main():
        out = []
        async for item in r.abatch_as_completed([1,1,2], {"max_concurrency": 1}):
            out.append(item)
        return out
    out = asyncio.run(main())
    idxs = [i for i,_ in out]
    print("abac max_concurrency:", out, calls)
    assert sorted(i for i,_ in out) == [0,1,2]
    assert abs(idxs.index(0)-idxs.index(1)) == 1
    assert len(calls) == 2

# sync batch_as_completed max_concurrency
def test_bac_max_concurrency():
    calls = []
    def f(x):
        time.sleep(0.05)
        calls.append(x)
        return x
    r = RunnableLambda(f).with_coalesce()
    out = list(r.batch_as_completed([1,1,2], {"max_concurrency": 1}))
    idxs = [i for i,_ in out]
    print("bac max_concurrency:", out, calls)
    assert abs(idxs.index(0)-idxs.index(1)) == 1
    assert len(calls) == 2

test_stream_callbacks()
test_abatch_max_concurrency()
test_abac_max_concurrency()
test_bac_max_concurrency()
print("ALL OK")
PYEOF
cd /app/libs/core && timeout 30 python /tmp/test_more_edge.py