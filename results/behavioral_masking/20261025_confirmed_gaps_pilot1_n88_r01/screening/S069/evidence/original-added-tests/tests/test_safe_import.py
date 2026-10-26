import io

import pytest

from sqlite_utils import Database
from sqlite_utils.db import (
    CheckpointNotActiveError,
    CheckpointNotFoundError,
    ImportInvariantError,
    SafeImportNotEnabledError,
)


def test_checkpoint_requires_enabled_safe_import():
    db = Database(memory=True)
    with pytest.raises(SafeImportNotEnabledError):
        db.create_import_checkpoint()


def test_checkpoint_commit_rollback_rules():
    db = Database(memory=True)
    db.enable_safe_import()
    checkpoint_id = db.create_import_checkpoint()
    assert isinstance(checkpoint_id, str) and checkpoint_id
    db.commit_checkpoint(checkpoint_id)
    with pytest.raises(CheckpointNotActiveError):
        db.commit_checkpoint(checkpoint_id)
    with pytest.raises(CheckpointNotActiveError):
        db.rollback_to_checkpoint(checkpoint_id)
    db.cleanup_checkpoint(checkpoint_id)
    with pytest.raises(CheckpointNotFoundError):
        db.commit_checkpoint(checkpoint_id)
    with pytest.raises(CheckpointNotFoundError):
        db.rollback_to_checkpoint(checkpoint_id)


def test_checkpoint_rollback_schema():
    db = Database(memory=True)
    db.enable_safe_import()
    checkpoint_id = db.create_import_checkpoint()
    db["t"].create({"id": int}, pk="id")
    db.execute("CREATE INDEX idx_t ON t(id)")
    db.execute("CREATE TRIGGER trg AFTER INSERT ON t BEGIN SELECT 1; END")
    db["t"].insert({"id": 1})
    db.rollback_to_checkpoint(checkpoint_id)
    db.cleanup_checkpoint(checkpoint_id)
    assert "t" not in db.table_names()
    assert db.triggers_dict == {}


def test_nested_checkpoints():
    db = Database(memory=True)
    db.enable_safe_import()
    outer = db.create_import_checkpoint()
    db["t"].create({"id": int}, pk="id")
    inner = db.create_import_checkpoint()
    db["t"].insert({"id": 1})
    db.rollback_to_checkpoint(inner)
    assert db["t"].count == 0
    db.commit_checkpoint(outer)
    assert db["t"].exists()
    with pytest.raises(CheckpointNotActiveError):
        db.commit_checkpoint(inner)


def test_import_invariants_crud_and_validation():
    db = Database(memory=True)
    db["t"].create({"id": int, "price": int})
    db["t"].insert_all([{"id": 1, "price": 5}, {"id": 2, "price": 10}])
    assert db.list_import_invariants("t") == []
    invariant_id = db.add_import_invariant("t", "COUNT(*) = 2")
    assert db.list_import_invariants("t") == [
        {"id": invariant_id, "expression": "COUNT(*) = 2"}
    ]
    assert db.validate_import_invariants("t") == {"valid": True, "failures": []}
    failing = db.add_import_invariant("t", "price > 5")
    result = db.validate_import_invariants("t")
    assert result["valid"] is False
    assert any(f["id"] == failing for f in result["failures"])
    assert all(
        set(f) == {"id", "expression", "error"} for f in result["failures"]
    )
    db.remove_import_invariant("t", failing)
    assert db.validate_import_invariants("t")["valid"] is True


def test_safe_bulk_insert_rolls_back_on_invariant_failure():
    db = Database(memory=True)
    db["t"].create({"id": int}, pk="id")
    db["t"].insert({"id": 1})
    db.add_import_invariant("t", "COUNT(*) <= 1")
    result = db["t"].safe_bulk_insert([{"id": 2}, {"id": 3}])
    assert result["success"] is False
    assert "checkpoint_id" in result
    assert "failures" in result
    assert "error_report" in result
    assert db["t"].count == 1
    # The returned checkpoint is finalized but can still be cleaned up
    with pytest.raises(CheckpointNotActiveError):
        db.rollback_to_checkpoint(result["checkpoint_id"])
    db.cleanup_checkpoint(result["checkpoint_id"])


def test_safe_bulk_insert_strict_raises_invariant_error():
    db = Database(memory=True)
    db["t"].create({"id": int}, pk="id")
    db.add_import_invariant("t", "COUNT(*) <= 0")
    with pytest.raises(ImportInvariantError) as exc:
        db["t"].safe_bulk_insert([{"id": 1}], strict=True)
    message = str(exc.value).lower()
    assert "valid" in message or "validation" in message or "invariant" in message
    assert db["t"].count == 0


def test_safe_bulk_upsert():
    db = Database(memory=True)
    db["t"].create({"id": int, "name": str}, pk="id")
    db["t"].insert({"id": 1, "name": "before"})
    db.add_import_invariant("t", "COUNT(*) <= 1")
    result = db["t"].safe_bulk_upsert([{"id": 2, "name": "new"}], pk="id")
    assert result["success"] is False
    assert db["t"].count == 1
    result = db["t"].safe_bulk_upsert([{"id": 1, "name": "after"}], pk="id")
    assert result["success"] is True
    assert db["t"].get(1)["name"] == "after"


def test_import_csv_and_json():
    db = Database(memory=True)
    assert db.import_csv("people", io.StringIO("id,name\n1,Alice\n2,Bob\n")) == {
        "success": True
    }
    assert db["people"].count == 2
    assert db.import_json("people", [{"id": 3, "name": "Carol"}]) == {"success": True}
    assert db["people"].count == 3
    db.add_import_invariant("people", "COUNT(*) <= 2")
    result = db.import_json("people", [{"id": 4, "name": "Dave"}], safe_mode=True)
    assert result["success"] is False
    assert db["people"].count == 3
