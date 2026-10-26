cd /app && python3 - <<'EOF'
from sqlite_utils import Database
db = Database(memory=True)
db.enable_safe_import()
c1 = db.create_import_checkpoint()
db["t"].insert({"id": 1}, pk="id")
c2 = db.create_import_checkpoint()
db["t"].insert({"id": 2}, pk="id")
db.rollback_to_checkpoint(c1)
print("tables after rollback outer:", db.table_names())
# inner c2 should now be unknown (not active/finalized)
try:
    db.commit_checkpoint(c2)
    print("ERROR: c2 still commit-able")
except Exception as e:
    print("c2 commit ->", type(e).__name__)
# outer rollback again -> NotActive
try:
    db.rollback_to_checkpoint(c1)
except Exception as e:
    print("c1 rollback again ->", type(e).__name__)
EOF
cd /app && python3 -m pytest tests/test_safe_import.py -q 2>&1 | tail -3