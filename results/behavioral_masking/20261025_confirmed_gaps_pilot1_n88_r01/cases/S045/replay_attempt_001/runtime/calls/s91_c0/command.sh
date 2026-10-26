cd /tmp && python - <<'PY'
s = open('/tmp/test_coalesce.py').read()

# fix batch test with slow function
old = '''def test_batch_coalesce():
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
    check("abatch positional", out == [2, 3, 2])'''
new = '''def test_batch_coalesce():
    calls = []
    def f(x):
        time.sleep(0.1)
        calls.append(x)
        return x + 1
    r = RunnableLambda(f).with_coalesce()
    out = r.batch([1, 2, 1, 1, 2])
    check("batch positional order", out == [2, 3, 2, 2, 3])
    check("batch coalesces", len(calls) == 2)  # only 1 and 2

    async def af(x):
        await asyncio.sleep(0.1)
        calls.append(x)
        return x + 1
    r2 = RunnableLambda(af).with_coalesce()
    async def main():
        return await r2.abatch([1, 2, 1])
    out = asyncio.run(main())
    check("abatch positional", out == [2, 3, 2])'''
assert old in s
s = s.replace(old, new, 1)

# fix clear sync waiter catch BaseException
old = '''    def leader():
        try:
            leader_result.append(r.invoke(1))
        except Exception as e:
            leader_result.append(e)
    def joiner():
        try:
            joiner_result.append(r.invoke(1))
        except Exception as e:
            joiner_result.append(e)'''
new = '''    def leader():
        try:
            leader_result.append(r.invoke(1))
        except BaseException as e:
            leader_result.append(e)
    def joiner():
        try:
            joiner_result.append(r.invoke(1))
        except BaseException as e:
            joiner_result.append(e)'''
assert old in s
s = s.replace(old, new, 1)

# fix clear async waiter catch BaseException
old = '''        async def leader():
            try:
                leader_res.append(await r.ainvoke(1))
            except Exception as e:
                leader_res.append(e)
        async def joiner():
            try:
                joiner_res.append(await r.ainvoke(1))
            except Exception as e:
                joiner_res.append(e)'''
new = '''        async def leader():
            try:
                leader_res.append(await r.ainvoke(1))
            except BaseException as e:
                leader_res.append(e)
        async def joiner():
            try:
                joiner_res.append(await r.ainvoke(1))
            except BaseException as e:
                joiner_res.append(e)'''
assert old in s
s = s.replace(old, new, 1)

# fix transform passthrough test
old = '''def test_transform_passthrough():
    calls = []
    def f(x):
        calls.append(x)
        return x
    r = RunnableLambda(f).with_coalesce()
    out = list(r.transform(iter([5, 6])))
    check("transform passthrough", out == [5, 6])
    # transform is not coalesced; each call runs
    check("transform not coalesced", len(calls) == 2)'''
new = '''def test_transform_passthrough():
    calls = []
    def f(x):
        calls.append(x)
        return x
    plain = RunnableLambda(f)
    r = plain.with_coalesce()
    out = list(r.transform(iter([5])))
    plain_out = list(plain.transform(iter([5])))
    check("transform passthrough", out == plain_out == [5])
    # transform is not coalesced; it delegates transparently to the bound runnable
    check("transform not coalesced", len(calls) == 2)'''
assert old in s
s = s.replace(old, new, 1)

open('/tmp/test_coalesce.py','w').write(s)
print("fixed tests")
PY
cd /app/libs/core && timeout 60 python /tmp/test_coalesce.py 2>&1 | tail -40