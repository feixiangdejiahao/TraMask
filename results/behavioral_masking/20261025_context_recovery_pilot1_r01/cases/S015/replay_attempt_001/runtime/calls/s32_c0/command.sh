cd /app && python - <<'PY'
path = 'bandit/formatters/json.py'
src = open(path).read()

old = '''    machine_output["metrics"] = manager.metrics.data

    # timezone agnostic format
'''
new = '''    machine_output["metrics"] = manager.metrics.data

    machine_output["cache_info"] = {
        "total_files": manager.cache_total_files,
        "cache_hits": manager.cache_hits,
        "cache_misses": manager.cache_misses,
        "invalidation_counts": {
            "file_changed": manager.invalidation_counts["file_changed"],
            "config_changed": manager.invalidation_counts["config_changed"],
            "expired": manager.invalidation_counts["expired"],
            "not_cached": manager.invalidation_counts["not_cached"],
        },
    }

    # timezone agnostic format
'''
assert old in src
src = src.replace(old, new, 1)
open(path, 'w').write(src)
PY
python -m py_compile bandit/formatters/json.py && echo OK