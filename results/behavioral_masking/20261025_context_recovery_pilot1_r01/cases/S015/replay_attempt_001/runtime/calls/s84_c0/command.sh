cd /app && python - <<'PY'
path = 'bandit/core/cache.py'
src = open(path).read()
old = '''        return (
            isinstance(entry, dict)
            and isinstance(entry.get("path"), str)
            and isinstance(entry.get("file_hash"), str)
            and isinstance(entry.get("issues"), list)
            and isinstance(entry.get("metrics"), dict)
            and isinstance(entry.get("cached_at"), (int, float))
            and isinstance(entry.get("cache_key"), str)
        )
'''
new = '''        return (
            isinstance(entry, dict)
            and isinstance(entry.get("path"), str)
            and isinstance(entry.get("file_hash"), str)
            and isinstance(entry.get("issues"), list)
            and isinstance(entry.get("metrics"), dict)
            and isinstance(entry.get("dependencies", []), list)
            and isinstance(entry.get("cached_at"), (int, float))
            and isinstance(entry.get("cache_key"), str)
        )
'''
assert old in src
src = src.replace(old, new, 1)
open(path, 'w').write(src)
PY
python -m py_compile bandit/core/cache.py && echo OK