cd /app && python3 - <<'EOF'
from sqlite_utils import Database
# failure then success
db = Database(memory=True)
db.enable_safe_import()
db.add_import_invariant("t", "COUNT(*) < 3")
r1 = db.safe_bulk_insert("t", [{"id": 1}, {"id": 2}, {"id": 3}], pk="id")
print("r1:", r1)
r2 = db.safe_bulk_insert("t", [{"id": 1}], pk="id")
print("r2:", r2, "count:", db["t"].count)

# failure then failure with different data
db2 = Database(memory=True)
db2["t"].insert({"id": 1}, pk="id")
r3 = db2.safe_bulk_insert("t", [{"id": 2}, {"id": 1}], pk="id", batch_size=1)
r4 = db2.safe_bulk_insert("t", [{"id": 2}], pk="id")
print("r3:", r3["success"], "r4:", r4["success"], "count:", db2["t"].count, list(db2["t"].rows))
EOF