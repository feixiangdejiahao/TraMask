cd /app/libs/core && python - <<'PY'
p = 'tests/unit_tests/runnables/test_imports.py'
s = open(p).read()
old = '''EXPECTED_ALL = [
    "chain",'''
new = '''EXPECTED_ALL = [
    "chain",
    "CoalesceBackend",
    "CoalesceStats",
    "InMemoryCoalesceBackend",'''
assert old in s
s = s.replace(old, new, 1)
open(p, 'w').write(s)
print("done")
PY
cat tests/unit_tests/runnables/test_imports.py | sed -n '1,40p'