cat > /tmp/test_other_runnables.py <<'PYEOF'
import asyncio, time, threading
from langchain_core.runnables import RunnableLambda, RunnableGenerator, RunnablePassthrough

# RunnableGenerator stream
calls = []
def gen(inputs):
    # transform-like generator
    for i in inputs:
        calls.append(i)
        yield i * 2

rg = RunnableGenerator(gen).with_coalesce()
out1 = list(rg.stream(5))
out2 = list(rg.stream(5))
print("RunnableGenerator stream:", out1, out2)

# RunnableGenerator async
calls2 = []
async def agen(inputs):
    async for i in inputs:
        calls2.append(i)
        yield i * 3

rag = RunnableGenerator(agen).with_coalesce()
async def main():
    a = []
    b = []
    async for chunk in rag.astream(2):
        a.append(chunk)
    async for chunk in rag.astream(2):
        b.append(chunk)
    return a, b
a, b = asyncio.run(main())
print("RunnableGenerator astream:", a, b)

# Sequence
def slow(x):
    time.sleep(0.2)
    return x + 1
seq = (RunnablePassthrough() | RunnableLambda(slow)).with_coalesce()
res = []
t1 = threading.Thread(target=lambda: res.append(seq.invoke(1)))
t2 = threading.Thread(target=lambda: res.append(seq.invoke(1)))
t1.start(); t2.start(); t1.join(); t2.join()
print("sequence invoke:", res)
print("sequence stats:", seq.coalesce_info())
PYEOF
cd /app/libs/core && timeout 30 python /tmp/test_other_runnables.py