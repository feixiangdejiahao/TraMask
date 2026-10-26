cat > /tmp/test_coalesce.py <<'PYEOF'
import asyncio
import threading
import time
import traceback
from collections import defaultdict

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.runnables import (
    InMemoryCoalesceBackend,
    RunnableLambda,
    RunnablePassthrough,
)

PASS = []
FAIL = []

def check(name, cond):
    if cond:
        PASS.append(name)
    else:
        FAIL.append(name)
        print(f"FAIL: {name}")

async def test_async_invoke():
    calls = []
    async def slow(x):
        await asyncio.sleep(0.2)
        calls.append(x)
        return x * 2

    r = RunnableLambda(slow).with_coalesce()
    results = await asyncio.gather(r.ainvoke(5), r.ainvoke(5), r.ainvoke(5))
    check("async invoke coalesces", results == [10, 10, 10])
    check("async invoke single execution", len(calls) == 1)
    stats = r.coalesce_info()
    check("stats active after", stats.active == 0)
    check("stats coalesced == 2", stats.coalesced == 2)
    check("stats total == 3", stats.total == 3)

def test_sync_invoke_threads():
    calls = []
    lock = threading.Lock()
    def slow(x):
        time.sleep(0.2)
        with lock:
            calls.append(x)
        return x * 2

    r = RunnableLambda(slow).with_coalesce()
    results = []
    threads = [threading.Thread(target=lambda: results.append(r.invoke(7))) for _ in range(3)]
    for t in threads: t.start()
    for t in threads: t.join()
    check("sync invoke coalesces", results == [14, 14, 14])
    check("sync invoke single execution", len(calls) == 1)

def test_dict_key_order():
    calls = []
    def f(d):
        calls.append(d)
        return sum(d.values())
    r = RunnableLambda(f).with_coalesce()
    async def main():
        a, b = await asyncio.gather(
            r.ainvoke({"a": 1, "b": 2}),
            r.ainvoke({"b": 2, "a": 1}),
        )
        return a, b
    a, b = asyncio.run(main())
    check("dict order coalesces", a == b == 3)
    check("dict order single execution", len(calls) == 1)

def test_config_kwargs_ignored():
    calls = []
    def f(x):
        calls.append(x)
        return x
    r = RunnableLambda(f).with_coalesce()
    async def main():
        a = r.ainvoke(1, config={"tags": ["a"]}, foo="bar")
        b = r.ainvoke(1, config={"tags": ["b"]}, baz=1)
        return await asyncio.gather(a, b)
    out = asyncio.run(main())
    check("config/kwargs coalesce", out == [1, 1])
    check("config/kwargs single execution", len(calls) == 1)

def test_fresh_after_complete():
    calls = []
    def f(x):
        calls.append(x)
        return x
    r = RunnableLambda(f).with_coalesce()
    assert r.invoke(1) == 1
    assert r.invoke(1) == 1
    check("fresh after complete", len(calls) == 2)

def test_stream_join_replays():
    def gen(x):
        yield from ["a", "b", "c"]

    r = RunnableLambda(gen).with_coalesce()

    async def main():
        it1 = r.astream(1)
        it2 = r.astream(1)
        c1 = await anext(it1)
        # ensure leader started
        await asyncio.sleep(0.05)
        c2 = await anext(it2)
        rest1 = [c async for c in it1]
        rest2 = [c async for c in it2]
        return [c1] + rest1, [c2] + rest2

    r1, r2 = asyncio.run(main())
    check("stream leader chunks", r1 == ["a", "b", "c"])
    check("stream joiner replays all", r2 == ["a", "b", "c"])

def test_stream_sync():
    def gen(x):
        yield from ["x", "y"]

    r = RunnableLambda(gen).with_coalesce()
    res1 = list(r.stream(1))
    res2 = list(r.stream(1))
    check("sync stream", res1 == ["x", "y"] and res2 == ["x", "y"])

def test_batch_coalesce():
    calls = []
    def f(x):
        calls.append(x)
        return x + 1
    r = RunnableLambda(f).with_coalesce()
    out = r.batch([1, 2, 1, 1, 2])
    check("batch positional order", out == [2, 3, 2, 2, 3])
    check("batch coalesces", len(calls) == 2)  # only 1 and 2

    async def main():
        return await r.abatch([1, 2, 1])
    out = asyncio.run(main())
    check("abatch positional", out == [2, 3, 2])

def test_batch_as_completed_consecutive():
    calls = []
    def f(x):
        time.sleep(0.1 * (x % 2))
        calls.append(x)
        return x * 10
    r = RunnableLambda(f).with_coalesce()
    # items: two 1s and one 2
    results = list(r.batch_as_completed([1, 1, 2]))
    idxs = [i for i, _ in results]
    # duplicates should be consecutive
    check("batch_as_completed all indices", sorted(i for i, _ in results) == [0, 1, 2])
    vals = [v for _, v in results]
    check("batch_as_completed values", sorted(vals) == [10, 10, 20])
    # find positions of 0 and 1 -> must be adjacent
    pos0 = idxs.index(0)
    pos1 = idxs.index(1)
    check("duplicates consecutive", abs(pos0 - pos1) == 1)
    check("batch_as_completed single execution for dup", calls.count(1) == 1)

async def test_abatch_as_completed_consecutive():
    calls = []
    async def f(x):
        await asyncio.sleep(0.1)
        calls.append(x)
        return x * 10
    r = RunnableLambda(f).with_coalesce()
    results = []
    async for item in r.abatch_as_completed([1, 1, 2, 2]):
        results.append(item)
    idxs = [i for i, _ in results]
    pos0, pos1 = idxs.index(0), idxs.index(1)
    pos2, pos3 = idxs.index(2), idxs.index(3)
    check("abatch_as_completed duplicates consecutive",
          abs(pos0 - pos1) == 1 and abs(pos2 - pos3) == 1)
    check("abatch_as_completed single execution per key", calls.count(1) == 1 and calls.count(2) == 1)

class CountHandler(BaseCallbackHandler):
    def __init__(self):
        self.starts = 0
        self.ends = 0
    def on_chain_start(self, *args, **kwargs):
        self.starts += 1
    def on_chain_end(self, *args, **kwargs):
        self.ends += 1

def test_join_callbacks_async():
    async def f(x):
        await asyncio.sleep(0.2)
        return x
    r = RunnableLambda(f).with_coalesce()
    h1, h2 = CountHandler(), CountHandler()
    async def main():
        return await asyncio.gather(
            r.ainvoke(1, {"callbacks": [h1]}),
            r.ainvoke(1, {"callbacks": [h2]}),
        )
    asyncio.run(main())
    check("joiner chain-start fired", h2.starts == 1)
    check("joiner chain-end fired", h2.ends == 1)
    check("leader chain-start fired", h1.starts == 1)
    check("leader chain-end fired", h1.ends == 1)

def test_join_callbacks_sync():
    def f(x):
        time.sleep(0.2)
        return x
    r = RunnableLambda(f).with_coalesce()
    h1, h2 = CountHandler(), CountHandler()
    res = []
    t1 = threading.Thread(target=lambda: res.append(r.invoke(1, {"callbacks": [h1]})))
    t2 = threading.Thread(target=lambda: res.append(r.invoke(1, {"callbacks": [h2]})))
    t1.start(); t2.start(); t1.join(); t2.join()
    check("sync joiner chain-start fired", h2.starts == 1)
    check("sync joiner chain-end fired", h2.ends == 1)

def test_error_propagation():
    def f(x):
        raise ValueError("boom")
    r = RunnableLambda(f).with_coalesce()
    async def main():
        results = await asyncio.gather(
            r.ainvoke(1), r.ainvoke(1), return_exceptions=True
        )
        return results
    results = asyncio.run(main())
    check("errors propagate to all", all(isinstance(r, ValueError) and str(r) == "boom" for r in results))

def test_clear_cancels_waiters():
    started = threading.Event()
    release = threading.Event()
    def slow(x):
        started.set()
        release.wait(2)
        return x
    r = RunnableLambda(slow).with_coalesce()
    leader_result = []
    joiner_result = []
    def leader():
        try:
            leader_result.append(r.invoke(1))
        except Exception as e:
            leader_result.append(e)
    def joiner():
        try:
            joiner_result.append(r.invoke(1))
        except Exception as e:
            joiner_result.append(e)
    t1 = threading.Thread(target=leader)
    t2 = threading.Thread(target=joiner)
    t1.start()
    started.wait(1)
    t2.start()
    time.sleep(0.2)  # ensure joiner is waiting
    r.coalesce_clear()
    t2.join(1)
    check("clear cancels sync waiter", len(joiner_result) == 1 and isinstance(joiner_result[0], asyncio.CancelledError))
    # leader still completes
    release.set()
    t1.join(2)
    check("leader completes after clear", leader_result == [1])
    stats = r.coalesce_info()
    check("clear resets stats", stats.active == 0 and stats.coalesced == 0 and stats.total == 0)

async def test_clear_cancels_async_waiters():
    started = asyncio.Event()
    release = asyncio.Event()
    async def slow(x):
        started.set()
        await release.wait()
        return x
    r = RunnableLambda(slow).with_coalesce()
    leader_res = []
    joiner_res = []
    async def leader():
        try:
            leader_res.append(await r.ainvoke(1))
        except Exception as e:
            leader_res.append(e)
    async def joiner():
        try:
            joiner_res.append(await r.ainvoke(1))
        except Exception as e:
            joiner_res.append(e)
    t1 = asyncio.create_task(leader())
    await started.wait()
    t2 = asyncio.create_task(joiner())
    await asyncio.sleep(0.1)
    r.coalesce_clear()
    await asyncio.sleep(0.1)
    check("clear cancels async waiter", len(joiner_res) == 1 and isinstance(joiner_res[0], asyncio.CancelledError))
    release.set()
    await t1
    check("async leader completes after clear", leader_res == [1])

def test_transform_passthrough():
    calls = []
    def f(x):
        calls.append(x)
        return x
    r = RunnableLambda(f).with_coalesce()
    out = list(r.transform(iter([5, 6])))
    check("transform passthrough", out == [5, 6])
    # transform is not coalesced; each call runs
    check("transform not coalesced", len(calls) == 2)

def test_shared_backend():
    calls = []
    def f(x):
        time.sleep(0.2)
        calls.append(x)
        return x
    backend = InMemoryCoalesceBackend()
    r1 = RunnableLambda(f).with_coalesce(backend=backend)
    r2 = RunnableLambda(f).with_coalesce(backend=backend)
    res = []
    t1 = threading.Thread(target=lambda: res.append(r1.invoke(1)))
    t2 = threading.Thread(target=lambda: res.append(r2.invoke(1)))
    t1.start(); t2.start(); t1.join(); t2.join()
    check("shared backend coalesces across wrappers", len(calls) == 1 and res == [1, 1])

def test_separate_wrappers_independent():
    calls = []
    def f(x):
        time.sleep(0.2)
        calls.append(x)
        return x
    r1 = RunnableLambda(f).with_coalesce()
    r2 = RunnableLambda(f).with_coalesce()
    res = []
    t1 = threading.Thread(target=lambda: res.append(r1.invoke(1)))
    t2 = threading.Thread(target=lambda: res.append(r2.invoke(1)))
    t1.start(); t2.start(); t1.join(); t2.join()
    check("separate wrappers independent", len(calls) == 2)

def test_graph_delegation():
    r = RunnableLambda(lambda x: x + 1).with_coalesce()
    graph = r.get_graph()
    check("graph delegation", graph is not None)

def test_sync_leader_async_joiner():
    started = threading.Event()
    release = threading.Event()
    def slow(x):
        started.set()
        release.wait(2)
        return x
    r = RunnableLambda(slow).with_coalesce()
    async_res = []
    def leader():
        r.invoke(1)
    t = threading.Thread(target=leader)
    t.start()
    started.wait(1)
    async def joiner():
        async_res.append(await r.ainvoke(1))
    asyncio.run(joiner())
    check("sync leader async joiner", async_res == [1])
    release.set()
    t.join(2)

def test_async_leader_sync_joiner():
    started = asyncio.Event()
    release = asyncio.Event()
    async def slow(x):
        started.set()
        await release.wait()
        return x
    r = RunnableLambda(slow).with_coalesce()
    sync_res = []
    async def leader():
        await r.ainvoke(1)
    t = threading.Thread(target=lambda: sync_res.append(r.invoke(1)))
    async def main():
        ltask = asyncio.create_task(leader())
        await started.wait()
        t.start()
        await asyncio.sleep(0.2)
        release.set()
        await ltask
    asyncio.run(main())
    t.join(2)
    check("async leader sync joiner", sync_res == [1])

async def main():
    await test_async_invoke()
    test_sync_invoke_threads()
    test_dict_key_order()
    test_config_kwargs_ignored()
    test_fresh_after_complete()
    test_stream_join_replays()
    test_stream_sync()
    test_batch_coalesce()
    test_batch_as_completed_consecutive()
    await test_abatch_as_completed_consecutive()
    test_join_callbacks_async()
    test_join_callbacks_sync()
    test_error_propagation()
    test_clear_cancels_waiters()
    await test_clear_cancels_async_waiters()
    test_transform_passthrough()
    test_shared_backend()
    test_separate_wrappers_independent()
    test_graph_delegation()
    test_sync_leader_async_joiner()
    test_async_leader_sync_joiner()

    print(f"\nPASS: {len(PASS)}")
    print(f"FAIL: {len(FAIL)}")
    for f in FAIL:
        print(" -", f)
    if FAIL:
        raise SystemExit(1)

asyncio.run(main())
PYEOF
cd /app/libs/core && timeout 120 python /tmp/test_coalesce.py