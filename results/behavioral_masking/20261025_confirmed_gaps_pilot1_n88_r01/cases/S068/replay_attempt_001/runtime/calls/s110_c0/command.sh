cd /app && python3 - <<'EOF'
from sqlite_utils import Database
# commit outer with active inner
db = Database(memory=True)
db.enable_safe_import()
c1 = db.create_import_checkpoint()
c2 = db.create_import_checkpoint()
db["t"].insert({"id": 1}, pk="id")
db.commit_checkpoint(c1)
try:
    db.commit_checkpoint(c2)
    print("ERROR: c2 still active")
except Exception as e:
    print("c2 after commit outer ->", type(e).__name__)
# cleanup outer with active inner
db2 = Database(memory=True)
db2.enable_safe_import()
d1 = db2.create_import_checkpoint()
d2 = db2.create_import_checkpoint()
db2.cleanup_checkpoint(d1)
try:
    db2.commit_checkpoint(d2)
    print("ERROR: d2 still active")
except Exception as e:
    print("d2 after cleanup outer ->", type(e).__name__)
# rollback outer with active inner
db3 = Database(memory=True)
db3.enable_safe_import()
e1 = db3.create_import_checkpoint()
e2 = db3.create_import_checkpoint()
db3["t"].insert({"id": 1}, pk="id")
db3.rollback_to_checkpoint(e1)
try:
    db3.commit_checkpoint(e2)
    print("ERROR: e2 still active")
except Exception as e:
    print("e2 after rollback outer ->", type(e).__name__)
EOF
cd /app && python3 -m pytest tests/test_safe_import.py -q 2>&1 | tail -3 && python3 -m pytest -q 2>&1 | tail -3