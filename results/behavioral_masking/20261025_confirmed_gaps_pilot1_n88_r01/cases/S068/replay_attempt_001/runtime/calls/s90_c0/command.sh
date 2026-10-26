cd /app && python3 - <<'PYEOF'
path = 'sqlite_utils/db.py'
src = open(path).read()

# cosmetic: remove double blank line before enable_safe_import
old = "        return list(self.query(sql, params))\n\n\n    def enable_safe_import"
new = "        return list(self.query(sql, params))\n\n    def enable_safe_import"
assert old in src
src = src.replace(old, new, 1)

# guard rollback when checkpoint_id is None
old = """            if not committed:
                try:
                    self.rollback_to_checkpoint(checkpoint_id)
                except Exception:
                    pass
"""
new = """            if not committed and checkpoint_id is not None:
                try:
                    self.rollback_to_checkpoint(checkpoint_id)
                except Exception:
                    pass
"""
assert old in src
src = src.replace(old, new, 1)

open(path, 'w').write(src)
print("done")
PYEOF
python3 -m py_compile sqlite_utils/db.py && python3 -m pytest tests/test_safe_import.py -q 2>&1 | tail -3