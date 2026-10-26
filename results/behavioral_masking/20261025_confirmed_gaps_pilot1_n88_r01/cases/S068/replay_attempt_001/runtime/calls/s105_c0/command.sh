cd /app && python3 - <<'EOF'
import sqlite3
conn = sqlite3.connect(":memory:")
conn.isolation_level = None
conn.execute("SAVEPOINT sp_outer")
conn.execute("SAVEPOINT sp_inner")
conn.execute("CREATE TABLE t (id integer)")
conn.execute("RELEASE SAVEPOINT sp_outer")
# Can we still release sp_inner?
try:
    conn.execute("RELEASE SAVEPOINT sp_inner")
    print("inner release ok")
except Exception as e:
    print("inner release err:", e)
print("tables:", conn.execute("select name from sqlite_master").fetchall())
EOF