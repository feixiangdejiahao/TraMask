cd /app && cat > /tmp/test_edge.py <<'EOF'
from sqlite_utils import Database

def t(name, fn):
    try:
        fn(); print("PASS:", name)
    except Exception as e:
        print("FAIL:", name, "->", type(e).__name__, e)

def nested_commit_then_outer_rollback():
    db = Database(memory=True)
    db.enable_safe_import()
    c1 = db.create_import_checkpoint()
    db["t"].insert({"id": 1}, pk="id")
    c2 = db.create_import_checkpoint()
    db["t"].insert({"id": 2}, pk="id")
    db.commit_checkpoint(c2)
    assert db["t"].count == 2
    db.rollback_to_checkpoint(c1)
    assert db["t"].count == 0, db["t"].count
t("nested commit then outer rollback", nested_commit_then_outer_rollback)

def cleanup_finalized():
    db = Database(memory=True)
    db.enable_safe_import()
    c1 = db.create_import_checkpoint()
    db["t"].insert({"id": 1}, pk="id")
    db.commit_checkpoint(c1)
    db.cleanup_checkpoint(c1)
    try:
        db.commit_checkpoint(c1); assert False
    except Exception as e:
        assert type(e).__name__ == "CheckpointNotFoundError"
t("cleanup finalized", cleanup_finalized)

def cleanup_unknown():
    db = Database(memory=True)
    db.enable_safe_import()
    try:
        db.cleanup_checkpoint("nope"); assert False
    except Exception as e:
        assert type(e).__name__ == "CheckpointNotFoundError"
t("cleanup unknown", cleanup_unknown)

def import_csv_path():
    import tempfile, os
    db = Database(memory=True)
    db.enable_safe_import()
    db.add_import_invariant("items", "COUNT(*) > 0")
    path = os.path.join(tempfile.mkdtemp(), "items.csv")
    open(path, "w").write("id,name\n1,a\n2,b\n")
    r = db.import_csv("items", path, safe_mode=True, pk="id")
    assert r == {"success": True}, r
    assert db["items"].count == 2
t("import_csv path", import_csv_path)

def import_json_string():
    db = Database(memory=True)
    db.enable_safe_import()
    r = db.import_json("items", '[{"id": 1, "name": "a"}]', safe_mode=True, pk="id")
    assert r == {"success": True}, r
    assert db["items"].count == 1
t("import_json string", import_json_string)

def strict_csv():
    import io
    db = Database(memory=True)
    db.enable_safe_import()
    db.add_import_invariant("items", "COUNT(*) < 1")
    try:
        db.import_csv("items", io.StringIO("id,name\n1,a\n"), safe_mode=True, strict=True, pk="id")
        assert False
    except Exception as e:
        assert "invariant" in str(e).lower() or "valid" in str(e).lower(), str(e)
    assert "items" not in db.table_names()
t("strict csv invariant raise", strict_csv)

def safe_import_no_autocommit_restore():
    db = Database(memory=True)
    old = db.conn.isolation_level
    db.safe_bulk_insert("t", [{"id": 1}], pk="id")
    assert db.conn.isolation_level == old
    # safe import enabled flag unchanged
    assert db._safe_import_enabled is False
    assert db._safe_import_in_progress is False
t("safe op restores state", safe_import_no_autocommit_restore)

def enable_disable_restores():
    db = Database(memory=True)
    old = db.conn.isolation_level
    db.enable_safe_import()
    assert db.conn.isolation_level is None
    assert db._safe_import_in_progress is True
    db.disable_safe_import()
    assert db.conn.isolation_level == old
    assert db._safe_import_in_progress is False
t("enable/disable restores", enable_disable_restores)
EOF
PYTHONPATH=/app python3 /tmp/test_edge.py