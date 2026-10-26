cd /app && python3 - <<'EOF'
import sqlite3
conn = sqlite3.connect(":memory:")
conn.isolation_level = None
print("before enter")
with conn:
    conn.execute("CREATE TABLE foo (id integer)")
    print("inside")
print("after with")
# did it commit? create table in autocommit is committed regardless
# test savepoint:
conn2 = sqlite3.connect(":memory:")
conn2.isolation_level = None
conn2.execute("SAVEPOINT sp1")
conn2.execute("CREATE TABLE foo (id integer)")
with conn2:
    print("entered with conn, isolation:", repr(conn2.isolation_level))
try:
    conn2.execute("ROLLBACK TO SAVEPOINT sp1")
    conn2.execute("RELEASE SAVEPOINT sp1")
    print("rollback ok")
except Exception as e:
    print("rollback err:", e)
    print("tables:", conn2.execute("select name from sqlite_master").fetchall())
EOF