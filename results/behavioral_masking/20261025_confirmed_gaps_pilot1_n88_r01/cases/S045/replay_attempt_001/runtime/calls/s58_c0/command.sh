cd /tmp && python - <<'PY'
s = open('/tmp/test_coalesce.py').read()
# replace async def test_async_invoke with def and body via asyncio.run
s = s.replace("""async def test_async_invoke():
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
    check("stats total == 3", stats.total == 3)""",
"""def test_async_invoke():
    calls = []
    async def slow(x):
        await asyncio.sleep(0.2)
        calls.append(x)
        return x * 2

    r = RunnableLambda(slow).with_coalesce()
    async def main():
        return await asyncio.gather(r.ainvoke(5), r.ainvoke(5), r.ainvoke(5))
    results = asyncio.run(main())
    check("async invoke coalesces", results == [10, 10, 10])
    check("async invoke single execution", len(calls) == 1)
    stats = r.coalesce_info()
    check("stats active after", stats.active == 0)
    check("stats coalesced == 2", stats.coalesced == 2)
    check("stats total == 3", stats.total == 3)""")

# Replace test_join_callbacks_async
s = s.replace("""def test_join_callbacks_async():
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
    check("leader chain-end fired", h1.ends == 1)""",
"""def test_join_callbacks_async():
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
    check("leader chain-end fired", h1.ends == 1)""")

# Replace async def test_abatch_as_completed_consecutive with def
s = s.replace("""async def test_abatch_as_completed_consecutive():
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
    check("abatch_as_completed single execution per key", calls.count(1) == 1 and calls.count(2) == 1)""",
"""def test_abatch_as_completed_consecutive():
    calls = []
    async def f(x):
        await asyncio.sleep(0.1)
        calls.append(x)
        return x * 10
    r = RunnableLambda(f).with_coalesce()
    async def main():
        results = []
        async for item in r.abatch_as_completed([1, 1, 2, 2]):
            results.append(item)
        return results
    results = asyncio.run(main())
    idxs = [i for i, _ in results]
    pos0, pos1 = idxs.index(0), idxs.index(1)
    pos2, pos3 = idxs.index(2), idxs.index(3)
    check("abatch_as_completed duplicates consecutive",
          abs(pos0 - pos1) == 1 and abs(pos2 - pos3) == 1)
    check("abatch_as_completed single execution per key", calls.count(1) == 1 and calls.count(2) == 1)""")

# Replace async def test_clear_cancels_async_waiters with def
s = s.replace("""async def test_clear_cancels_async_waiters():
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
    check("async leader completes after clear", leader_res == [1])""",
"""def test_clear_cancels_async_waiters():
    started = asyncio.Event()
    release = asyncio.Event()
    async def slow(x):
        started.set()
        await release.wait()
        return x
    r = RunnableLambda(slow).with_coalesce()
    async def main():
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
    asyncio.run(main())""")

# Replace async def test_sync_leader_async_joiner with def
s = s.replace("""def test_sync_leader_async_joiner():
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
    t.join(2)""",
"""def test_sync_leader_async_joiner():
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
    t.join(2)""")

# Replace async def test_async_leader_sync_joiner with def
s = s.replace("""def test_async_leader_sync_joiner():
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
    check("async leader sync joiner", sync_res == [1])""",
"""def test_async_leader_sync_joiner():
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
    check("async leader sync joiner", sync_res == [1])""")

# Fix main to be sync
s = s.replace("""async def main():
    await test_async_invoke()
    test_sync_invoke_threads()""",
"""def main():
    test_async_invoke()
    test_sync_invoke_threads()""")
s = s.replace("""    test_batch_as_completed_consecutive()
    await test_abatch_as_completed_consecutive()
    test_join_callbacks_async()""",
"""    test_batch_as_completed_consecutive()
    test_abatch_as_completed_consecutive()
    test_join_callbacks_async()""")
s = s.replace("""    test_clear_cancels_waiters()
    await test_clear_cancels_async_waiters()
    test_transform_passthrough()""",
"""    test_clear_cancels_waiters()
    test_clear_cancels_async_waiters()
    test_transform_passthrough()""")
s = s.replace("""    print(f"\\nPASS: {len(PASS)}")
    print(f"FAIL: {len(FAIL)}")
    for f in FAIL:
        print(" -", f)
    if FAIL:
        raise SystemExit(1)

asyncio.run(main())""",
"""    print(f"\\nPASS: {len(PASS)}")
    print(f"FAIL: {len(FAIL)}")
    for f in FAIL:
        print(" -", f)
    if FAIL:
        raise SystemExit(1)

main()""")
open('/tmp/test_coalesce.py','w').write(s)
print("fixed")
PY
cd /app/libs/core && timeout 120 python /tmp/test_coalesce.py