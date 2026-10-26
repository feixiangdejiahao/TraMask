cd /app && python - <<'PY'
import sys
files = [
    'bandit/core/cache.py',
    'bandit/core/manager.py',
    'bandit/core/metrics.py',
    'bandit/formatters/json.py',
    'bandit/formatters/text.py',
    'bandit/cli/main.py',
    'tests/functional/test_incremental.py',
    'tests/unit/core/test_cache.py',
    'tests/unit/core/test_manager_cache.py',
]
for fn in files:
    for i, line in enumerate(open(fn), 1):
        if len(line.rstrip('\n')) > 79:
            print(f'{fn}:{i}: {len(line.rstrip())} chars')
PY