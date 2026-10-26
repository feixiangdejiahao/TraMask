cd /app && python - <<'PY'
path = 'bandit/core/manager.py'
src = open(path).read()

old = """        self.metrics = metrics.Metrics()
        self.b_ts = b_test_set.BanditTestSet(config, profile)
        self.scores = []
"""
new = """        self.metrics = metrics.Metrics()
        self.b_ts = b_test_set.BanditTestSet(config, profile)
        self.scores = []
        self.cache = None
        self.cache_hits = 0
        self.cache_misses = 0
        self.cache_total_files = 0
        self.files_cached = []
        self.files_scanned = []
        self.invalidation_counts = {
            "file_changed": 0,
            "config_changed": 0,
            "expired": 0,
            "not_cached": 0,
        }
        self.invalidation_reasons = {}
"""
assert old in src
src = src.replace(old, new, 1)
open(path, 'w').write(src)
PY
grep -n "cache_hits\|cache_misses\|cache_total_files\|files_cached\|invalidation" bandit/core/manager.py | head -20