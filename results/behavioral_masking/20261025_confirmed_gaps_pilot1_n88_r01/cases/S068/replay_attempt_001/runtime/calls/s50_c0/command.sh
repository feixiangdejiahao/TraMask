cd /app && python3 - <<'EOF'
import sqlite_utils
db = sqlite_utils.Database(memory=True)
db.enable_safe_import()
print("isolation:", repr(db.conn.isolation_level))
db.execute("SAVEPOINT \"sp_abc\"")
print("saved")
# use raw execute, not table method
db.execute("CREATE TABLE foo (id integer)")
try:
    db.execute("ROLLBACK TO SAVEPOINT \"sp_abc\"")
    db.execute("RELEASE SAVEPOINT \"sp_abc\"")
    print("rollback ok, tables:", db.table_names())
except Exception as e:
    print("rollback err:", e)
EOF