cd /app && cat > /tmp/test_safe.py <<'EOF'
import io, json
from sqlite_utils import Database

def t(name, fn):
    try:
        fn()
        print("PASS:", name)
    except Exception as e:
        print("FAIL:", name, "->", type(e).__name__, e)
        import traceback; traceback.print_exc()

# --- Checkpoint basics ---
def cp_basic():
    db = Database(memory=True)
    db["t"].insert({"id": 1, "name": "one"}, pk="id")
    db.enable_safe_import()
    cid = db.create_import_checkpoint()
    assert isinstance(cid, str) and cid
    db["t"].insert({"id": 2, "name": "two"}, pk="id")
    db.rollback_to_checkpoint(cid)
    assert db["t"].count == 1, db["t"].count
    try:
        db.rollback_to_checkpoint(cid)
        assert False
    except Exception as e:
        assert type(e).__name__ == "CheckpointNotActiveError", e
    try:
        db.commit_checkpoint("nope")
        assert False
    except Exception as e:
        assert type(e).__name__ == "CheckpointNotFoundError", e
    # cleanup finalized
    db.cleanup_checkpoint(cid)
    try:
        db.commit_checkpoint(cid)
        assert False
    except Exception as e:
        assert type(e).__name__ == "CheckpointNotFoundError", e
t("checkpoint basics", cp_basic)

def cp_commit():
    db = Database(memory=True)
    db.enable_safe_import()
    cid = db.create_import_checkpoint()
    db["t"].insert({"id": 1, "name": "one"}, pk="id")
    db.commit_checkpoint(cid)
    assert db["t"].count == 1
    try:
        db.commit_checkpoint(cid)
        assert False
    except Exception as e:
        assert type(e).__name__ == "CheckpointNotActiveError"
t("checkpoint commit", cp_commit)

def cp_nested():
    db = Database(memory=True)
    db.enable_safe_import()
    cid1 = db.create_import_checkpoint()
    db["t"].insert({"id": 1}, pk="id")
    cid2 = db.create_import_checkpoint()
    db["t"].insert({"id": 2}, pk="id")
    db.rollback_to_checkpoint(cid2)
    assert db["t"].count == 1
    db.commit_checkpoint(cid1)
    assert db["t"].count == 1
t("nested checkpoints", cp_nested)

def cp_cleanup_active():
    db = Database(memory=True)
    db.enable_safe_import()
    cid = db.create_import_checkpoint()
    db["t"].insert({"id": 1}, pk="id")
    db.cleanup_checkpoint(cid)
    assert db["t"].count == 1  # cleanup releases (keeps writes)
    try:
        db.commit_checkpoint(cid)
        assert False
    except Exception as e:
        assert type(e).__name__ == "CheckpointNotFoundError"
t("cleanup active", cp_cleanup_active)

# --- Invariants ---
def inv_basic():
    db = Database(memory=True)
    db["items"].insert_all([{"id": 1, "name": "a"}, {"id": 2, "name": "b"}], pk="id")
    iid = db.add_import_invariant("items", "COUNT(*) = 2")
    assert isinstance(iid, str) and iid
    result = db.validate_import_invariants("items")
    assert result == {"valid": True, "failures": []}, result
    listed = db.list_import_invariants("items")
    assert listed == [{"id": iid, "expression": "COUNT(*) = 2"}], listed
    db.remove_import_invariant("items", iid)
    assert db.list_import_invariants("items") == []
t("invariant basic", inv_basic)

def inv_fail():
    db = Database(memory=True)
    db["items"].insert_all([{"id": 1, "name": "a"}], pk="id")
    db.add_import_invariant("items", "COUNT(*) > 1")
    result = db.validate_import_invariants("items")
    assert result["valid"] is False
    assert len(result["failures"]) == 1
    assert result["failures"][0]["id"]
    assert result["failures"][0]["expression"] == "COUNT(*) > 1"
t("invariant fail", inv_fail)

def inv_rowwise():
    db = Database(memory=True)
    db["items"].insert_all([{"id": 1, "name": "a"}, {"id": 2, "name": "b"}], pk="id")
    db.add_import_invariant("items", "id > 0")
    assert db.validate_import_invariants("items")["valid"] is True
    db["items"].insert({"id": -1, "name": "neg"}, pk="id")
    result = db.validate_import_invariants("items")
    assert result["valid"] is False
    # select-style invariant
    db2 = Database(memory=True)
    db2["x"].insert({"a": 1})
    db2.add_import_invariant("x", "SELECT a = 1 FROM x")
    assert db2.validate_import_invariants("x")["valid"] is True
    db2["x"].insert({"a": 0})
    assert db2.validate_import_invariants("x")["valid"] is False
t("invariant rowwise + select", inv_rowwise)

# --- Safe operations ---
def safe_success():
    db = Database(memory=True)
    db.enable_safe_import()
    db.add_import_invariant("items", "COUNT(*) > 0")
    result = db.safe_bulk_insert("items", [{"id": 1, "name": "a"}, {"id": 2, "name": "b"}], pk="id")
    assert result == {"success": True}, result
    assert db["items"].count == 2
t("safe bulk insert success", safe_success)

def safe_insert_fail_rollback():
    db = Database(memory=True)
    db["items"].insert({"id": 1, "name": "a"}, pk="id")
    result = db.safe_bulk_insert("items", [
        {"id": 2, "name": "b"},
        {"id": 3, "name": "c"},
        {"id": 1, "name": "dup"},
    ], pk="id", batch_size=1)
    assert result["success"] is False
    assert result["checkpoint_id"]
    assert "UNIQUE constraint failed" in result["error_report"] or "Import error" in result["error_report"]
    assert db["items"].count == 1, db["items"].count  # no partial insert of id 2,3
    assert [r["id"] for r in db["items"].rows] == [1]
t("safe insert fail rollback", safe_insert_fail_rollback)

def safe_invariant_fail_rollback():
    db = Database(memory=True)
    db.enable_safe_import()
    db.add_import_invariant("items", "COUNT(*) < 2")
    result = db.safe_bulk_insert("items", [{"id": 1, "name": "a"}, {"id": 2, "name": "b"}], pk="id")
    assert result["success"] is False
    assert len(result["failures"]) == 1
    assert "invariant" in result["error_report"].lower() or "valid" in result["error_report"].lower()
    assert db.table_names() == [] or "items" not in db.table_names(), db.table_names()
t("safe invariant fail rollback", safe_invariant_fail_rollback)

def safe_strict_raise():
    db = Database(memory=True)
    db.enable_safe_import()
    db.add_import_invariant("items", "COUNT(*) < 2")
    try:
        db.safe_bulk_insert("items", [{"id": 1}, {"id": 2}], pk="id", strict=True)
        assert False
    except Exception as e:
        msg = str(e).lower()
        assert "invariant" in msg or "valid" in msg or "validation" in msg, msg
    # operation error raises original
    db2 = Database(memory=True)
    db2["t"].insert({"id": 1}, pk="id")
    try:
        db2.safe_bulk_insert("t", [{"id": 2}, {"id": 1}], pk="id", batch_size=1, strict=True)
        assert False
    except Exception as e:
        assert "UNIQUE" in str(e), str(e)
t("safe strict raise", safe_strict_raise)

def safe_schema_rollback():
    db = Database(memory=True)
    db["existing"].insert({"id": 1, "name": "a"}, pk="id")
    db.create_index("existing", ["name"], unique=True)
    db.execute("CREATE TRIGGER existing_trig AFTER INSERT ON existing BEGIN SELECT 1; END")
    before_schema = db.schema
    before_tables = db.table_names()
    before_triggers = db.triggers_dict
    result = db.safe_bulk_insert(
        "new_table",
        [{"id": 1, "name": "x"}, {"id": 2, "name": "x"}],
        pk="id",
        batch_size=1,
    )
    # duplicate pk? no - new table no duplicate. Make it fail via invariant
    db2 = Database(memory=True)
    db2.enable_safe_import()
    db2.add_import_invariant("new_table", "COUNT(*) < 2")
    result2 = db2.safe_bulk_insert("new_table", [{"id": 1}, {"id": 2}], pk="id")
    assert result2["success"] is False
    assert "new_table" not in db2.table_names(), db2.table_names()
    # index/trigger rollback
    db3 = Database(memory=True)
    db3["t"].insert({"id": 1, "name": "a"}, pk="id")
    db3.create_index("t", ["name"])
    db3.execute("CREATE TRIGGER trg AFTER INSERT ON t BEGIN SELECT 1; END")
    before_schema3 = db3.schema
    db3.enable_safe_import()
    db3.add_import_invariant("t", "COUNT(*) < 2")
    result3 = db3.safe_bulk_insert("t", [{"id": 2, "name": "b"}], pk="id")
    assert result3["success"] is False
    assert db3.schema == before_schema3, (before_schema3, db3.schema)
    assert db3.table_names() == ["t"]
    assert set(db3.triggers_dict.keys()) == {"trg"}
    assert db3["t"].indexes[0].name  # index still there
t("safe schema rollback", safe_schema_rollback)

def safe_upsert():
    db = Database(memory=True)
    db["t"].insert({"id": 1, "name": "a"}, pk="id")
    db.enable_safe_import()
    db.add_import_invariant("t", "COUNT(*) < 3")
    r = db.safe_bulk_upsert("t", [{"id": 1, "name": "b"}, {"id": 2, "name": "c"}], pk="id")
    assert r == {"success": True}, r
    assert db["t"].count == 2
    db2 = Database(memory=True)
    db2["t"].insert({"id": 1, "name": "a"}, pk="id")
    db2.enable_safe_import()
    db2.add_import_invariant("t", "COUNT(*) < 2")
    r2 = db2.safe_bulk_upsert("t", [{"id": 1, "name": "b"}, {"id": 2, "name": "c"}], pk="id")
    assert r2["success"] is False
    assert db2["t"].count == 1
    assert db2["t"].get(1)["name"] == "a"
t("safe upsert", safe_upsert)

def import_csv_json():
    db = Database(memory=True)
    db.enable_safe_import()
    db.add_import_invariant("items", "COUNT(*) > 0")
    csv_text = "id,name\n1,a\n2,b\n"
    r = db.import_csv("items", io.StringIO(csv_text), safe_mode=True, pk="id")
    assert r == {"success": True}, r
    assert db["items"].count == 2
    r2 = db.import_json("items", [{"id": 3, "name": "c"}], safe_mode=True, pk="id")
    assert r2 == {"success": True}
    assert db["items"].count == 3
    # failure via invariant
    db2 = Database(memory=True)
    db2.enable_safe_import()
    db2.add_import_invariant("items", "COUNT(*) < 1")
    r3 = db2.import_csv("items", io.StringIO("id,name\n1,a\n"), safe_mode=True, pk="id")
    assert r3["success"] is False
    assert "items" not in db2.table_names()
t("import csv/json", import_csv_json)

def safe_bulk_execute_update():
    db = Database(memory=True)
    db["t"].insert_all([{"id": 1, "name": "a"}, {"id": 2, "name": "b"}], pk="id")
    db.enable_safe_import()
    r = db.safe_bulk_execute(
        "UPDATE t SET name = :name WHERE id = :id",
        [{"id": 1, "name": "x"}, {"id": 2, "name": "y"}],
    )
    assert r == {"success": True}, r
    assert db["t"].get(1)["name"] == "x"
    assert db["t"].get(2)["name"] == "y"
t("safe bulk execute update", safe_bulk_execute_update)
EOF
PYTHONPATH=/app python3 /tmp/test_safe.py