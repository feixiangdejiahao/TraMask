cd /app && python3 - <<'EOF'
import sqlite3
conn = sqlite3.connect(":memory:")
try:
    conn.commit = lambda: None
    print("assigned commit ok")
    conn.execute("SAVEPOINT sp1")
    conn.execute("CREATE TABLE foo (id integer)")
    with conn:
        print("with conn entered")
    conn.execute("ROLLBACK TO SAVEPOINT sp1")
    conn.execute("RELEASE SAVEPOINT sp1")
    print("rollback ok, tables:", conn.execute("select name from sqlite_master").fetchall())
    print("commit is noop:", conn.commit)
except Exception as e:
    import traceback; traceback.print_exc()
EOF