cat > /tmp/test_coalesce_edge.py <<'PYEOF'
import asyncio
import threading
import time

from langchain_core.runnables import (
    InMemoryCoalesceBackend,
    RunnableLambda,
    RunnablePassthrough,
)

PASS = []
FAIL = []
def check(name, cond):
    if cond: PASS.append(name)
    else:
        FAIL.append(name)
        print("FAIL:", name)

def test_astream_events_passthrough():
    async def f(x):
        await asyncio.sleep(0.01)
        return x * 2
    r = RunnableLambda(f).with_coalesce()
    events = []
    async def main():
        async for ev in r.astream_events(1, version="v2"):
            events.append(ev["event"])
        return events
    events = asyncio.run(main())
    check("astream_events passthrough", any(e.startswith("on_chain_") for e in events))

def test_batch_return_exceptions():
    calls = []
    def f(x):
        time.sleep(0.05)
        calls.append(x)
        if x == 3:
            raise ValueError("bad 3")
        return x + 1
    r = RunnableLambda(f).with_coalesce()
    out = r.batch([1, 1, 3, 3], return_exceptions=True)
    check("batch return_exceptions results", out[0] == 2 and out[1] == 2)
    check("batch return_exceptions errors", all(isinstance(o, ValueError) for o in out[2:]))
    check("batch return_exceptions coalesce", len(calls) == 2)  # 1 and 3

def test_batch_as_completed_return_exceptions():
    calls = []
    def f(x):
        time.sleep(0.05)
        calls.append(x)
        if x == 3:
            raise ValueError("bad 3")
        return x + 1
    r = RunnableLambda(f).with_coalesce()
    results = list(r.batch_as_completed([1, 1, 3, 3], return_exceptions=True))
    vals = [v for _, v in results]
    check("bac return_exceptions results", 2 in vals and isinstance(vals[vals.index(2) + 1], int) if vals.count(2) == 2 else False)
    check("bac return_exceptions errors", sum(isinstance(v, ValueError) for v in vals) == 2)

def test_stats_during_execution():
    started = threading.Event()
    release = threading.Event()
    def f(x):
        started.set()
        release.wait(2)
        return x
    r = RunnableLambda(f).with_coalesce()
    stats_snapshot = []
    t = threading.Thread(target=lambda: r.invoke(1))
    t.start()
    started.wait(1)
    stats_snapshot.append(r.coalesce_info())
    release.set()
    t.join(2)
    check("stats active during", stats_snapshot[0].active == 1)
    check("stats total during", stats_snapshot[0].total == 1)
    check("stats active after", r.coalesce_info().active == 0)

def test_backend_direct_api():
    b = InMemoryCoalesceBackend()
    check("register leader", b.register("k") is True)
    check("is_active", b.is_active("k") is True)
    check("register joiner", b.register("k") is False)
    check("stats coalesced", b.stats.coalesced == 1)
    check("stats total", b.stats.total == 2)
    b.complete("k", result="res")
    check("complete is_active", b.is_active("k") is False)
    check("join returns result", b.join("k") == "res")
    # fresh after complete
    check("register after complete fresh", b.register("k") is True)
    b.complete("k", result="res2")
    check("join fresh result", b.join("k") == "res2")

def test_backend_direct_async_api():
    b = InMemoryCoalesceBackend()
    async def main():
        a1 = await b.aregister("k")
        a2 = await b.aregister("k")
        active = await b.ais_active("k")
        await b.acomplete("k", result="res")
        joined = await b.ajoin("k")
        return a1, a2, active, joined, b.stats
    a1, a2, active, joined, stats = asyncio.run(main())
    check("async backend register", a1 is True and a2 is False)
    check("async backend active", active is True)
    check("async backend join", joined == "res")
    check("async backend stats", stats.coalesced == 1 and stats.total == 2)

def test_backend_async_join_wait():
    b = InMemoryCoalesceBackend()
    async def main():
        assert await b.aregister("k")
        result = []
        async def joiner():
            result.append(await b.ajoin("k"))
        t = asyncio.create_task(joiner())
        await asyncio.sleep(0.05)
        check("async join pending", not result)
        await b.acomplete("k", result="done")
        await t
        check("async join wakes", result == ["done"])
    asyncio.run(main())

def test_stream_error_propagation():
    async def gen(x):
        yield "a"
        raise ValueError("boom")
    r = RunnableLambda(gen).with_coalesce()
    async def main():
        it1 = r.astream(1)
        it2 = r.astream(1)
        out1 = await anext(it1)
        joiner_task = asyncio.create_task(anext(it2))
        await asyncio.sleep(0.05)
        try:
            rest1 = [c async for c in it1]
        except ValueError as e:
            rest1 = e
        try:
            out2 = await joiner_task
            rest2 = [c async for c in it2]
        except ValueError as e:
            out2 = e
            rest2 = []
        return out1, rest1, out2, rest2
    out1, rest1, out2, rest2 = asyncio.run(main())
    check("stream leader error", out1 == "a" and isinstance(rest1, ValueError))
    check("stream joiner error", isinstance(out2, ValueError))

def test_nested_dict_canonical():
    b = InMemoryCoalesceBackend()
    d1 = {"a": {"x": 1, "y": 2}, "b": [1, 2]}
    d2 = {"b": [1, 2], "a": {"y": 2, "x": 1}}
    check("nested dict canonical", b.register(d1) is True and b.register(d2) is False)

def test_with_coalesce_on_binding():
    def f(x, extra=0):
        return x + extra
    base = RunnableLambda(f).bind(extra=10)
    r = base.with_coalesce()
    out = r.invoke(1)
    check("with_coalesce on binding", out == 11)
    async def main():
        return await asyncio.gather(r.ainvoke(1), r.ainvoke(1))
    outs = asyncio.run(main())
    check("binding async coalesce", outs == [11, 11])

def test_clear_resets_and_allows_fresh():
    calls = []
    def f(x):
        calls.append(x)
        return x
    r = RunnableLambda(f).with_coalesce()
    assert r.invoke(1) == 1
    r.coalesce_clear()
    stats = r.coalesce_info()
    check("clear resets", stats.total == 0 and stats.coalesced == 0 and stats.active == 0)
    assert r.invoke(1) == 1
    check("fresh after clear", len(calls) == 2)

def test_chain_composition():
    calls = []
    def f(x):
        time.sleep(0.1)
        calls.append(x)
        return x + 1
    inner = RunnableLambda(f).with_coalesce()
    outer = RunnablePassthrough() | inner
    async def main():
        return await asyncio.gather(outer.ainvoke(5), outer.ainvoke(5))
    out = asyncio.run(main())
    check("chain coalesce", out == [6, 6] and len(calls) == 1)

def main():
    test_astream_events_passthrough()
    test_batch_return_exceptions()
    test_batch_as_completed_return_exceptions()
    test_stats_during_execution()
    test_backend_direct_api()
    test_backend_direct_async_api()
    test_backend_async_join_wait()
    test_stream_error_propagation()
    test_nested_dict_canonical()
    test_with_coalesce_on_binding()
    test_clear_resets_and_allows_fresh()
    test_chain_composition()
    print(f"\nPASS: {len(PASS)} FAIL: {len(FAIL)}")
    for f in FAIL:
        print(" -", f)
    if FAIL:
        raise SystemExit(1)

main()
PYEOF
cd /app/libs/core && timeout 60 python /tmp/test_coalesce_edge.py