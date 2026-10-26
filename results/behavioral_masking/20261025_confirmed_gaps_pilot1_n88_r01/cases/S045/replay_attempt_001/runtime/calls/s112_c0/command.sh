cat > /tmp/test_cross_method.py <<'PYEOF'
import asyncio, threading, time
from langchain_core.runnables import RunnableLambda

# batch item coalesces with concurrent invoke
calls = []
def f(x):
    time.sleep(0.3)
    calls.append(x)
    return x * 10

r = RunnableLambda(f).with_coalesce()
res = []
t = threading.Thread(target=lambda: res.append(r.invoke(1)))
t.start()
time.sleep(0.05)
batch_res = r.batch([1, 2])
t.join()
print("invoke+batch:", res, batch_res, "calls", calls, "stats", r.coalesce_info())

# async batch item coalesces with async invoke
calls2 = []
async def af(x):
    await asyncio.sleep(0.3)
    calls2.append(x)
    return x * 10

r2 = RunnableLambda(af).with_coalesce()
async def main():
    t = asyncio.create_task(r2.ainvoke(1))
    await asyncio.sleep(0.05)
    batch_res = await r2.abatch([1, 2])
    inv = await t
    return inv, batch_res
inv, batch_res = asyncio.run(main())
print("ainvoke+abatch:", inv, batch_res, "calls", calls2, "stats", r2.coalesce_info())
PYEOF
cd /app/libs/core && timeout 20 python /tmp/test_cross_method.py