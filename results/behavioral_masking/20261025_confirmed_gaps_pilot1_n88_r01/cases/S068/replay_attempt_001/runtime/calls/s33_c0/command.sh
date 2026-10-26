git checkout -b safe-import && cat > /tmp/repro.py <<'EOF'
import sqlite_utils
from sqlite_utils import Database

# Demonstrate partial failure: insert_all commits chunks independently
db = Database(memory=True)
db["items"].insert_all([
    {"id": 1, "name": "one"},
    {"id": 2, "name": "two"},
], pk="id")
print("before:", list(db["items"].rows))

# Now a bulk insert that will fail on the 2nd record due to NOT NULL
# With batch_size=1, first insert commits, second fails -> partial state remains
try:
    db["items"].insert_all([
        {"id": 3, "name": "three"},
        {"id": 4, "name": "four"},
    ], pk="id", batch_size=1)
except Exception as e:
    print("error:", e)
# But if we try to trigger failure: insert duplicate pk with batch_size=1, first succeeds then second fails
db2 = Database(memory=True)
db2["items"].insert_all([{"id": 1, "name": "one"}], pk="id")
try:
    db2["items"].insert_all([
        {"id": 2, "name": "two"},
        {"id": 1, "name": "duplicate"},
    ], pk="id", batch_size=1)
except Exception as e:
    print("error:", e)
print("after partial failure rows:", list(db2["items"].rows))
print("rows count:", db2["items"].count)

# Desired API checks
try:
    db3 = Database(memory=True)
    db3.create_import_checkpoint()
except Exception as e:
    print("create without enable ->", type(e).__name__, str(e))
db3.enable_safe_import()
cid = db3.create_import_checkpoint()
print("checkpoint id:", repr(cid), "non-empty:", bool(cid))
db3.rollback_to_checkpoint(cid)
try:
    db3.rollback_to_checkpoint(cid)
except Exception as e:
    print("double rollback ->", type(e).__name__)
EOF
python3 /tmp/repro.py