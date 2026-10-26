cd /app && python3 - <<'PYEOF'
path = 'sqlite_utils/db.py'
src = open(path).read()
old = "        self.strict = strict\n"
new = """        self.strict = strict
        self._safe_import_enabled = False
        self._active_checkpoints = set()
        self._finalized_checkpoints = set()
        self._safe_import_previous_isolation_level = None
"""
assert old in src
src = src.replace(old, new, 1)
open(path, 'w').write(src)
print("done")
PYEOF