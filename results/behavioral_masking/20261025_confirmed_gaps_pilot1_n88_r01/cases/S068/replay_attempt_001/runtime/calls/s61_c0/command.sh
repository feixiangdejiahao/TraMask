cd /app && python3 - <<'PYEOF'
path = 'sqlite_utils/db.py'
src = open(path).read()
src = src.replace(
    '''"INSERT INTO {} (\\\"table\\\", id, expression) VALUES (?, ?, ?)"''',
    ''''INSERT INTO {} ("table", id, expression) VALUES (?, ?, ?)''',
)
# Fix what currently exists (unescaped)
src = src.replace(
    '''"INSERT INTO {} ("table", id, expression) VALUES (?, ?, ?)"''',
    ''''INSERT INTO {} ("table", id, expression) VALUES (?, ?, ?)''',
)
src = src.replace(
    '''"DELETE FROM {} WHERE \\\"table\\\" = ? AND id = ?"''',
    ''''DELETE FROM {} WHERE "table" = ? AND id = ?''',
)
src = src.replace(
    '''"DELETE FROM {} WHERE "table" = ? AND id = ?"''',
    ''''DELETE FROM {} WHERE "table" = ? AND id = ?''',
)
src = src.replace(
    '''"SELECT id, expression FROM {} WHERE \\\"table\\\" = ? ORDER BY rowid"''',
    ''''SELECT id, expression FROM {} WHERE "table" = ? ORDER BY rowid''',
)
src = src.replace(
    '''"SELECT id, expression FROM {} WHERE "table" = ? ORDER BY rowid"''',
    ''''SELECT id, expression FROM {} WHERE "table" = ? ORDER BY rowid''',
)
open(path, 'w').write(src)
print("done")
PYEOF
python3 -m py_compile sqlite_utils/db.py && echo OK