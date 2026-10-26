cd /app && python3 - <<'EOF'
from sqlite_utils import Database
db = Database(memory=True)
db.enable_safe_import()
c1 = db.create_import_checkpoint()
db["t"].insert({"id": 1}, pk="id")
c2 = db.create_import_checkpoint()
db["t"].insert({"id": 2}, pk="id")
db.cleanup_checkpoint(c2)
print("after cleanup c2:", db["t"].count)
db.rollback_to_checkpoint(c1)
print("after rollback c1:", db.table_names())
EOF