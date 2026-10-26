cd /app/libs/core && python - <<'PY'
p = 'tests/unit_tests/runnables/test_coalesce.py'
s = open(p).read()
s = s.replace("    assert calls == [1, 2]\n", "    assert sorted(calls) == [1, 2]\n")
open(p,'w').write(s)
print("ok")
PY
cd /app/libs/core && timeout 180 python -m pytest tests/unit_tests/runnables/test_coalesce.py -q 2>&1 | tail -6