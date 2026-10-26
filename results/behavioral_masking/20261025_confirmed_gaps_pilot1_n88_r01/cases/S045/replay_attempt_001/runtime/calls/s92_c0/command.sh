cat > /tmp/cbdebug.py <<'PYEOF'
import asyncio
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.runnables import RunnableLambda

class CountHandler(BaseCallbackHandler):
    def __init__(self):
        self.starts = 0
        self.ends = 0
        self.errors = 0
    def on_chain_start(self, *args, **kwargs):
        self.starts += 1
        print("start", kwargs.get("name"), args, flush=True)
    def on_chain_end(self, *args, **kwargs):
        self.ends += 1
        print("end", kwargs.get("name"), flush=True)

async def main():
    async def f(x):
        await asyncio.sleep(0.2)
        return x
    r = RunnableLambda(f).with_coalesce()
    h1, h2 = CountHandler(), CountHandler()
    await asyncio.gather(
        r.ainvoke(1, {"callbacks": [h1]}),
        r.ainvoke(1, {"callbacks": [h2]}),
    )
    print("h1 starts", h1.starts, "ends", h1.ends)
    print("h2 starts", h2.starts, "ends", h2.ends)

asyncio.run(main())
PYEOF
cd /app/libs/core && timeout 20 python /tmp/cbdebug.py 2>&1 | head -40