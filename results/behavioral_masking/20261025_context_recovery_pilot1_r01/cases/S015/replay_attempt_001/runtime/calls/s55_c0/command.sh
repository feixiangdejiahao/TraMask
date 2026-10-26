cd /app && python - <<'PY'
path = 'tests/unit/core/test_cache.py'
src = open(path).read()
old = '''    def test_corrupted_cache_file(self):
        with open(self.cache.cache_path, "w") as f:
            f.write("{broken")
        loaded = b_cache.BanditCache(self.cache_dir, cache_key="key1")
        self.assertEqual({}, loaded.entries)
'''
new = '''    def test_corrupted_cache_file(self):
        os.makedirs(self.cache_dir, exist_ok=True)
        with open(self.cache.cache_path, "w") as f:
            f.write("{broken")
        loaded = b_cache.BanditCache(self.cache_dir, cache_key="key1")
        self.assertEqual({}, loaded.entries)
'''
assert old in src
src = src.replace(old, new, 1)
open(path, 'w').write(src)
PY
timeout 120 python -m pytest tests/unit/core/test_cache.py -q 2>&1 | tail -8