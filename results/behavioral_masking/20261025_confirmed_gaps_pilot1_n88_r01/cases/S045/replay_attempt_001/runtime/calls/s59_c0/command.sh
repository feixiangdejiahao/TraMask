cd /tmp && python - <<'PY'
s = open('/tmp/test_coalesce.py').read()
old = '''def test_config_kwargs_ignored():
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
    check("config/kwargs single execution", len(calls) == 1)'''
new = '''def test_config_kwargs_ignored():
    calls = []
    def f(x, **kwargs):
        calls.append(x)
        return x
    r = RunnableLambda(f).with_coalesce()
    async def main():
        a = r.ainvoke(1, config={"tags": ["a"]}, foo="bar")
        b = r.ainvoke(1, config={"tags": ["b"]}, baz=1)
        return await asyncio.gather(a, b)
    out = asyncio.run(main())
    check("config/kwargs coalesce", out == [1, 1])
    check("config/kwargs single execution", len(calls) == 1)'''
assert old in s
s = s.replace(old, new, 1)
open('/tmp/test_coalesce.py','w').write(s)
print("fixed")
PY
cd /app/libs/core && timeout 120 python /tmp/test_coalesce.py