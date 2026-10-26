cd /tmp && python - <<'PY'
s = open('/tmp/test_coalesce.py').read()
old = '''def test_stream_join_replays():
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
    check("stream joiner replays all", r2 == ["a", "b", "c"])'''
new = '''def test_stream_join_replays():
    async def gen(x):
        yield "a"
        await asyncio.sleep(0.05)
        yield "b"
        yield "c"

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
    check("stream joiner replays all", r2 == ["a", "b", "c"])'''
assert old in s
s = s.replace(old, new, 1)
open('/tmp/test_coalesce.py','w').write(s)
print("fixed")
PY
cd /app/libs/core && timeout 120 python /tmp/test_coalesce.py