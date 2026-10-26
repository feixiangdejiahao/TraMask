cd /app/libs/core && python - <<'PY'
p = 'langchain_core/runnables/coalesce.py'
s = open(p).read()
# add helper after _canonical_key
helper = '''async def _aiter_single(value: Any) -> AsyncIterator[Any]:
    """Return an async iterator that yields a single value."""
    yield value


'''
anchor = "class _SyncWaiter:"
assert anchor in s
s = s.replace(anchor, helper + anchor, 1)
# replace aiter([input]) usage
s = s.replace("aiter([input]),", "_aiter_single(input),")
open(p, 'w').write(s)
print("done")
PY
cd /app/libs/core && timeout 120 python /tmp/test_coalesce.py