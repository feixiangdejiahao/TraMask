cd /tmp && python - <<'PY'
s = open('/tmp/test_coalesce.py').read()
old = '''    async def main():
        it1 = r.astream(1)
        it2 = r.astream(1)
        c1 = await anext(it1)
        # ensure leader started
        await asyncio.sleep(0.05)
        c2 = await anext(it2)
        rest1 = [c async for c in it1]
        rest2 = [c async for c in it2]
        return [c1] + rest1, [c2] + rest2'''
new = '''    async def main():
        it1 = r.astream(1)
        it2 = r.astream(1)
        c1 = await anext(it1)
        # ensure leader is in flight
        await asyncio.sleep(0.05)
        # start consuming the joiner; it blocks until the leader completes
        joiner_first = asyncio.create_task(anext(it2))
        await asyncio.sleep(0.05)
        rest1 = [c async for c in it1]
        c2 = await joiner_first
        rest2 = [c async for c in it2]
        return [c1] + rest1, [c2] + rest2'''
assert old in s
s = s.replace(old, new, 1)
open('/tmp/test_coalesce.py','w').write(s)
print("ok")
PY
cd /app/libs/core && timeout 25 python /tmp/test_coalesce.py 2>&1 | tail -40