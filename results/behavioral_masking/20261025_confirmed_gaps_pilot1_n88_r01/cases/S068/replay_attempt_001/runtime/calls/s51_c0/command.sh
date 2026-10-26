cd /app && python3 - <<'EOF'
import sqlite_utils
db = sqlite_utils.Database(memory=True)
db.enable_safe_import()
db.execute("SAVEPOINT \"sp_abc\"")
db["t"].insert({"id": 1})
print("after insert, isolation:", repr(db.conn.isolation_level))
try:
    db.execute("ROLLBACK TO SAVEPOINT \"sp_abc\"")
    db.execute("RELEASE SAVEPOINT \"sp_abc\"")
    print("rollback ok, tables:", db.table_names())
except Exception as e:
    print("rollback err:", e)
    print("tables now:", db.table_names())
EOF