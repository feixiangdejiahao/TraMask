from sqlite_utils import Database, cli
from sqlite_utils.db import (
    CheckpointNotActiveError,
    CheckpointNotFoundError,
    ImportInvariantValidationError,
    SafeImportNotEnabledError,
)
from click.testing import CliRunner
import json
import pathlib
import pytest


@pytest.fixture
def safe_db():
    db = Database(memory=True)
    db.enable_safe_import()
    return db


def test_create_checkpoint_requires_enable():
    db = Database(memory=True)
    with pytest.raises(SafeImportNotEnabledError):
        db.create_import_checkpoint()
    with pytest.raises(SafeImportNotEnabledError):
        db.safe_bulk_insert("t", [{"id": 1}])


def test_checkpoint_lifecycle(safe_db):
    checkpoint_id = safe_db.create_import_checkpoint()
    assert checkpoint_id
    safe_db["t"].insert({"id": 1})
    safe_db.rollback_to_checkpoint(checkpoint_id)
    assert "t" not in safe_db.table_names()
    with pytest.raises(CheckpointNotActiveError):
        safe_db.rollback_to_checkpoint(checkpoint_id)
    safe_db.cleanup_checkpoint(checkpoint_id)
    with pytest.raises(CheckpointNotFoundError):
        safe_db.cleanup_checkpoint(checkpoint_id)


def test_commit_checkpoint(safe_db):
    checkpoint_id = safe_db.create_import_checkpoint()
    safe_db["t"].insert({"id": 1})
    safe_db.commit_checkpoint(checkpoint_id)
    assert safe_db["t"].count == 1
    with pytest.raises(CheckpointNotActiveError):
        safe_db.commit_checkpoint(checkpoint_id)


def test_nested_checkpoints(safe_db):
    outer = safe_db.create_import_checkpoint()
    safe_db["t"].insert({"id": 1})
    inner = safe_db.create_import_checkpoint()
    safe_db["t"].insert({"id": 2})
    safe_db.rollback_to_checkpoint(inner)
    assert safe_db["t"].count == 1
    safe_db.commit_checkpoint(outer)
    assert safe_db["t"].count == 1


def test_schema_rollback(safe_db):
    checkpoint_id = safe_db.create_import_checkpoint()
    safe_db.execute("create table t (id integer primary key, name text)")
    safe_db.execute("create index idx_t on t(name)")
    safe_db.execute("create trigger trg after insert on t begin update t set name = name; end")
    safe_db.execute("alter table t add column age integer")
    safe_db.rollback_to_checkpoint(checkpoint_id)
    assert "t" not in safe_db.table_names()
    assert safe_db.triggers == []


def test_invariants_crud(safe_db):
    safe_db["t"].insert({"id": 1})
    invariant_id = safe_db.add_import_invariant("t", "COUNT(*) = 1")
    assert safe_db.list_import_invariants("t") == [
        {"id": invariant_id, "expression": "COUNT(*) = 1"}
    ]
    assert safe_db.validate_import_invariants("t") == {
        "valid": True,
        "failures": [],
    }
    safe_db.remove_import_invariant("t", invariant_id)
    assert safe_db.list_import_invariants("t") == []


def test_safe_bulk_insert_commit(safe_db):
    assert safe_db.safe_bulk_insert("t", [{"id": 1}, {"id": 2}]) == {
        "success": True
    }
    assert safe_db["t"].count == 2


def test_safe_bulk_insert_invariant_failure(safe_db):
    safe_db.add_import_invariant("t", "COUNT(*) = 1")
    result = safe_db.safe_bulk_insert("t", [{"id": 1}, {"id": 2}])
    assert result["success"] is False
    assert "checkpoint_id" in result
    assert result["failures"]
    assert "t" not in safe_db.table_names()


def test_safe_bulk_insert_strict(safe_db):
    safe_db.add_import_invariant("t", "COUNT(*) = 1")
    with pytest.raises(ImportInvariantValidationError) as ex:
        safe_db.safe_bulk_insert("t", [{"id": 1}, {"id": 2}], strict=True)
    assert "validation" in str(ex.value) or "invariant" in str(ex.value)
    assert "t" not in safe_db.table_names()


def test_safe_bulk_upsert(safe_db):
    assert safe_db.safe_bulk_upsert("t", [{"id": 1, "name": "a"}], pk="id") == {
        "success": True
    }
    assert safe_db.safe_bulk_upsert("t", [{"id": 1, "name": "b"}], pk="id") == {
        "success": True
    }
    assert list(safe_db["t"].rows) == [{"id": 1, "name": "b"}]


def test_import_json(safe_db):
    assert safe_db.import_json("t", [{"id": 1}], safe_mode=True) == {
        "success": True
    }
    safe_db.add_import_invariant("t", "COUNT(*) = 1")
    assert safe_db.import_json("t", [{"id": 2}], safe_mode=True)["success"] is False
    assert safe_db["t"].count == 1


def test_import_csv(safe_db, tmpdir):
    path = str(tmpdir / "data.csv")
    with open(path, "w") as fp:
        fp.write("id,name\n1,Alice\n2,Bob\n")
    safe_db.add_import_invariant("t", "COUNT(*) = 2")
    assert safe_db.import_csv("t", path, safe_mode=True) == {"success": True}
    assert safe_db["t"].count == 2


def test_non_aggregate_invariant(safe_db):
    safe_db.add_import_invariant("t", "id < 10")
    assert safe_db.safe_bulk_insert("t", [{"id": 1}, {"id": 2}]) == {
        "success": True
    }
    result = safe_db.safe_bulk_insert("t", [{"id": 100}])
    assert result["success"] is False
    assert safe_db["t"].count == 2


def test_select_invariant(safe_db):
    safe_db.add_import_invariant("t", "SELECT COUNT(*) = 2 FROM t")
    assert safe_db.safe_bulk_insert("t", [{"id": 1}, {"id": 2}]) == {
        "success": True
    }
    result = safe_db.safe_bulk_insert("t", [{"id": 3}])
    assert result["success"] is False
    assert safe_db["t"].count == 2


def test_persistence(tmpdir):
    path = str(tmpdir / "data.db")
    db = Database(path)
    db.enable_safe_import()
    db.add_import_invariant("t", "COUNT(*) >= 0")
    db.close()
    db2 = Database(path)
    assert db2._safe_import_enabled
    assert db2.list_import_invariants("t")
    db2.disable_safe_import()
    db2.close()
    assert Database(path)._safe_import_enabled is False


def test_cli_safe_mode_insert(tmpdir):
    db_path = str(tmpdir / "data.db")
    runner = CliRunner()
    result = runner.invoke(
        cli.cli, ["enable-safe-import", db_path]
    )
    assert result.exit_code == 0
    result = runner.invoke(
        cli.cli, ["add-import-invariant", db_path, "t", "COUNT(*) = 2"]
    )
    assert result.exit_code == 0
    result = runner.invoke(
        cli.cli,
        ["insert", db_path, "t", "-", "--safe-mode"],
        input=json.dumps([{"id": 1}, {"id": 2}]),
    )
    assert result.exit_code == 0
    db = Database(db_path)
    assert db["t"].count == 2
    result = runner.invoke(
        cli.cli,
        ["insert", db_path, "t", "-", "--safe-mode"],
        input=json.dumps([{"id": 3}]),
    )
    assert result.exit_code != 0
    assert db["t"].count == 2


def test_cli_safe_mode_bulk_update(tmpdir):
    db_path = str(tmpdir / "data.db")
    db = Database(db_path)
    db["example"].insert_all([{"id": 1, "name": "One"}], pk="id")
    db.close()
    runner = CliRunner()
    result = runner.invoke(
        cli.cli,
        [
            "bulk",
            db_path,
            "update example set name = :name where id = :id",
            "-",
            "--nl",
            "--safe-mode",
        ],
        input='{"id": 1, "name": "OneUpdated"}\n',
    )
    assert result.exit_code == 0
    db = Database(db_path)
    assert list(db["example"].rows) == [{"id": 1, "name": "OneUpdated"}]


def test_cli_list_and_validate_invariants(tmpdir):
    db_path = str(tmpdir / "data.db")
    runner = CliRunner()
    runner.invoke(cli.cli, ["enable-safe-import", db_path])
    runner.invoke(
        cli.cli, ["add-import-invariant", db_path, "t", "SELECT 1"]
    )
    result = runner.invoke(cli.cli, ["list-import-invariants", db_path, "t"])
    assert result.exit_code == 0
    assert "1" in result.output
    assert "SELECT 1" in result.output
    result = runner.invoke(cli.cli, ["validate-import-invariants", db_path, "t"])
    assert result.exit_code == 0
    assert "Pass" in result.output or "Fail" in result.output
