cd /app && python3 - <<'PYEOF'
path = 'sqlite_utils/db.py'
lines = open(path).read().split('\n')

# Fix line indices (1-based)
fixes = {
    1016: "                'INSERT INTO {} (\"table\", id, expression) VALUES (?, ?, ?)'.format(",
    1033: "                'DELETE FROM {} WHERE \"table\" = ? AND id = ?'.format(",
    1048: "            'SELECT id, expression FROM {} WHERE \"table\" = ? ORDER BY rowid'.format(",
}
for lineno, text in fixes.items():
    assert lines[lineno-1].strip().startswith(("'INSERT", "'DELETE", "'SELECT")), (lineno, lines[lineno-1])
    lines[lineno-1] = text

open(path, 'w').write('\n'.join(lines))
print("fixed")
PYEOF
python3 -m py_compile sqlite_utils/db.py && echo OK