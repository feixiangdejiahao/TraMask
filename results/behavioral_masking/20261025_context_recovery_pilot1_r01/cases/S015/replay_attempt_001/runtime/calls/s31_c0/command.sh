cd /app && python - <<'PY'
path = 'bandit/core/metrics.py'
src = open(path).read()
old = '''        self.data["_totals"] = {
            "loc": 0,
            "nosec": 0,
            "skipped_tests": 0,
        }
'''
new = '''        self.data["_totals"] = {
            "loc": 0,
            "nosec": 0,
            "skipped_tests": 0,
            "cache_hits": 0,
            "cache_misses": 0,
        }
'''
assert old in src
src = src.replace(old, new, 1)
open(path, 'w').write(src)
PY
python -m py_compile bandit/core/metrics.py && echo OK