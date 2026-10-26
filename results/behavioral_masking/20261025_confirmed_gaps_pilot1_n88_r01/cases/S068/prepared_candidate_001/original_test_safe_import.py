import io
import json
from click.testing import CliRunner
import pytest
from sqlite_utils import Database, cli
from sqlite_utils.db import (
    CheckpointNotActiveError,
    CheckpointNotFoundError,
    ImportInvariantError,
    SafeImportNotEnabledError,
)


@pytest.fixture
def safe_db():
    db = Database(memory=True)
    db.enable_safe_import()
    return db


def test_create_checkpoint_requires_safe_import():
    db = Database(memory=True)
    with pytest.raises(SafeImportNotEnabledError):
        db.create_import_checkpoint()


def test_checkpoint_commit_and_rollback_finalize():
    db = Database(memory=True)
    db.enable_safe_import()
    checkpoint_id = db.create_import_checkpoint()
    assert checkpoint_id
    db["t"].insert({"id": 1}, pk="id")
    db.commit_checkpoint(checkpoint_id)
    assert db["t"].count == 1
    with pytest.raises(CheckpointNotActiveError):
        db.commit_checkpoint(checkpoint_id)
    with pytest.raises(CheckpointNotActiveError):
        db.rollback_to_checkpoint(checkpoint_id)


def test_checkpoint_rollback_restores_data_and_schema():
    db = Database(memory=True)
    db.enable_safe_import()
    db["t"].insert({"id": 1, "name": "a"}, pk="id")
    db["t"].create_index(["name"])
    db.execute("CREATE TRIGGER trg AFTER INSERT ON t BEGIN SELECT 1; END")
    checkpoint_id = db.create_import_checkpoint()
    db["t"].insert({"id": 2, "name": "b"}, pk="id")
    db["t"].add_column("extra", str)
    db.execute("CREATE INDEX idx2 ON t (extra)")
    db.rollback_to_checkpoint(checkpoint_id)
    assert db["t"].count == 1
    assert [c.name for c in db["t"].columns] == ["id", "name"]
    assert [i.name for i in db["t"].indexes] == [db["t"].indexes[0].name]
    assert set(db.triggers_dict.keys()) == {"trg"}


def test_checkpoint_unknown_and_cleanup():
    db = Database(memory=True)
    db.enable_safe_import()
    checkpoint_id = db.create_import_checkpoint()
    db.cleanup_checkpoint(checkpoint_id)
    with pytest.raises(CheckpointNotFoundError):
        db.commit_checkpoint(checkpoint_id)
    with pytest.raises(CheckpointNotFoundError):
        db.rollback_to_checkpoint(checkpoint_id)
    with pytest.raises(CheckpointNotFoundError):
        db.cleanup_checkpoint("missing")


def test_nested_checkpoints():
    db = Database(memory=True)
    db.enable_safe_import()
    outer = db.create_import_checkpoint()
    db["t"].insert({"id": 1}, pk="id")
    inner = db.create_import_checkpoint()
    db["t"].insert({"id": 2}, pk="id")
    db.rollback_to_checkpoint(inner)
    assert db["t"].count == 1
    db.commit_checkpoint(outer)
    assert db["t"].count == 1


def test_import_invariant_lifecycle():
    db = Database(memory=True)
    db["items"].insert_all([{"id": 1}, {"id": 2}], pk="id")
    invariant_id = db.add_import_invariant("items", "COUNT(*) = 2")
    assert invariant_id
    assert db.list_import_invariants("items") == [
        {"id": invariant_id, "expression": "COUNT(*) = 2"}
    ]
    assert db.validate_import_invariants("items") == {"valid": True, "failures": []}
    db.remove_import_invariant("items", invariant_id)
    assert db.list_import_invariants("items") == []


def test_import_invariant_failures():
    db = Database(memory=True)
    db["items"].insert_all([{"id": 1}, {"id": 2}], pk="id")
    db.add_import_invariant("items", "COUNT(*) > 2")
    result = db.validate_import_invariants("items")
    assert result["valid"] is False
    assert len(result["failures"]) == 1
    assert set(result["failures"][0].keys()) == {"id", "expression", "error"}


def test_import_invariant_aggregate_and_rowwise():
    db = Database(memory=True)
    db["items"].insert_all([{"id": 1}, {"id": 2}], pk="id")
    db.add_import_invariant("items", "COUNT(*) = 2")
    db.add_import_invariant("items", "id > 0")
    assert db.validate_import_invariants("items")["valid"] is True
    db["items"].insert({"id": -1}, pk="id")
    result = db.validate_import_invariants("items")
    assert result["valid"] is False
    assert len(result["failures"]) == 2


def test_import_invariant_select():
    db = Database(memory=True)
    db["items"].insert({"id": 1}, pk="id")
    db.add_import_invariant("items", "SELECT id = 1 FROM items")
    assert db.validate_import_invariants("items")["valid"] is True


def test_safe_bulk_insert_success(safe_db):
    safe_db.add_import_invariant("items", "COUNT(*) > 0")
    result = safe_db.safe_bulk_insert(
        "items",
        [{"id": 1, "name": "a"}, {"id": 2, "name": "b"}],
        pk="id",
    )
    assert result == {"success": True}
    assert safe_db["items"].count == 2


def test_safe_bulk_insert_rolls_back_on_error():
    db = Database(memory=True)
    db["items"].insert({"id": 1}, pk="id")
    result = db.safe_bulk_insert(
        "items",
        [{"id": 2}, {"id": 3}, {"id": 1}],
        pk="id",
        batch_size=1,
    )
    assert result["success"] is False
    assert result["checkpoint_id"]
    assert result["failures"] == []
    assert "Import error" in result["error_report"]
    assert db["items"].count == 1


def test_safe_bulk_insert_rolls_back_on_invariant(safe_db):
    safe_db.add_import_invariant("items", "COUNT(*) < 2")
    result = safe_db.safe_bulk_insert(
        "items", [{"id": 1}, {"id": 2}], pk="id"
    )
    assert result["success"] is False
    assert len(result["failures"]) == 1
    assert "invariant" in result["error_report"].lower()
    assert "items" not in safe_db.table_names()


def test_safe_bulk_insert_strict_raises(safe_db):
    safe_db.add_import_invariant("items", "COUNT(*) < 2")
    with pytest.raises(ImportInvariantError) as excinfo:
        safe_db.safe_bulk_insert("items", [{"id": 1}, {"id": 2}], pk="id", strict=True)
    message = str(excinfo.value).lower()
    assert "valid" in message or "validation" in message or "invariant" in message


def test_safe_bulk_upsert(safe_db):
    safe_db["t"].insert({"id": 1, "name": "a"}, pk="id")
    safe_db.add_import_invariant("t", "COUNT(*) < 3")
    result = safe_db.safe_bulk_upsert(
        "t", [{"id": 1, "name": "b"}, {"id": 2, "name": "c"}], pk="id"
    )
    assert result == {"success": True}
    assert safe_db["t"].get(1)["name"] == "b"
    assert safe_db["t"].count == 2


def test_safe_bulk_execute_update(safe_db):
    safe_db["t"].insert_all([{"id": 1, "name": "a"}, {"id": 2, "name": "b"}], pk="id")
    result = safe_db.safe_bulk_execute(
        "UPDATE t SET name = :name WHERE id = :id",
        [{"id": 1, "name": "x"}, {"id": 2, "name": "y"}],
    )
    assert result == {"success": True}
    assert safe_db["t"].get(1)["name"] == "x"
    assert safe_db["t"].get(2)["name"] == "y"


def test_import_csv(safe_db):
    safe_db.add_import_invariant("items", "COUNT(*) > 0")
    result = safe_db.import_csv(
        "items", io.StringIO("id,name\n1,a\n2,b\n"), safe_mode=True, pk="id"
    )
    assert result == {"success": True}
    assert safe_db["items"].count == 2


def test_import_json(safe_db):
    result = safe_db.import_json(
        "items", [{"id": 1, "name": "a"}], safe_mode=True, pk="id"
    )
    assert result == {"success": True}
    assert safe_db["items"].count == 1


def test_import_json_string(safe_db):
    result = safe_db.import_json(
        "items", '[{"id": 1, "name": "a"}]', safe_mode=True, pk="id"
    )
    assert result == {"success": True}
    assert safe_db["items"].count == 1


@pytest.fixture
def cli_db_path(tmpdir):
    from sqlite_utils.utils import sqlite3
    path = str(tmpdir / "data.db")
    db = sqlite3.connect(path)
    db.execute("create table items (id integer primary key, name text)")
    db.commit()
    db.close()
    return path


def test_cli_safe_insert_success(cli_db_path):
    result = CliRunner().invoke(
        cli.cli,
        ["insert", cli_db_path, "items", "-", "--pk", "id", "--safe-mode"],
        input=json.dumps({"id": 1, "name": "a"}),
    )
    assert result.exit_code == 0, result.output
    assert Database(cli_db_path)["items"].count == 1


def test_cli_safe_insert_failure(cli_db_path):
    db = Database(cli_db_path)
    db.add_import_invariant("items", "COUNT(*) < 1")
    result = CliRunner().invoke(
        cli.cli,
        ["insert", cli_db_path, "items", "-", "--pk", "id", "--safe-mode"],
        input=json.dumps({"id": 1, "name": "a"}),
    )
    assert result.exit_code != 0
    assert Database(cli_db_path)["items"].count == 0


def test_cli_safe_bulk_update(cli_db_path):
    db = Database(cli_db_path)
    db["items"].insert({"id": 1, "name": "a"}, pk="id")
    result = CliRunner().invoke(
        cli.cli,
        [
            "bulk",
            cli_db_path,
            "update items set name = :name where id = :id",
            "-",
            "--nl",
            "--safe-mode",
        ],
        input='{"id": 1, "name": "updated"}\n',
    )
    assert result.exit_code == 0, result.output
    assert Database(cli_db_path)["items"].get(1)["name"] == "updated"


def test_cli_import_invariant_commands(cli_db_path):
    runner = CliRunner()
    result = runner.invoke(cli.cli, ["add-import-invariant", cli_db_path, "items", "COUNT(*) >= 0"])
    assert result.exit_code == 0
    invariant_id = result.output.strip()
    assert invariant_id
    result = runner.invoke(cli.cli, ["list-import-invariants", cli_db_path, "items"])
    assert result.exit_code == 0
    assert invariant_id in result.output
    assert "COUNT(*) >= 0" in result.output
    result = runner.invoke(cli.cli, ["validate-import-invariants", cli_db_path, "items"])
    assert result.exit_code == 0
    assert "Pass" in result.output
    result = runner.invoke(cli.cli, ["remove-import-invariant", cli_db_path, "items", invariant_id])
    assert result.exit_code == 0
    result = runner.invoke(cli.cli, ["list-import-invariants", cli_db_path, "items"])
    assert invariant_id not in result.output


def test_nested_checkpoint_outer_commit_invalidates_inner():
    db = Database(memory=True)
    db.enable_safe_import()
    outer = db.create_import_checkpoint()
    inner = db.create_import_checkpoint()
    db["t"].insert({"id": 1}, pk="id")
    db.commit_checkpoint(outer)
    with pytest.raises(CheckpointNotFoundError):
        db.commit_checkpoint(inner)
    assert db["t"].count == 1


def test_nested_checkpoint_outer_rollback_invalidates_inner():
    db = Database(memory=True)
    db.enable_safe_import()
    outer = db.create_import_checkpoint()
    inner = db.create_import_checkpoint()
    db["t"].insert({"id": 1}, pk="id")
    db.rollback_to_checkpoint(outer)
    with pytest.raises(CheckpointNotFoundError):
        db.commit_checkpoint(inner)
    assert db.table_names() == []


def test_cleanup_active_releases_and_removes():
    db = Database(memory=True)
    db.enable_safe_import()
    checkpoint_id = db.create_import_checkpoint()
    db["t"].insert({"id": 1}, pk="id")
    db.cleanup_checkpoint(checkpoint_id)
    assert db["t"].count == 1
    with pytest.raises(CheckpointNotFoundError):
        db.commit_checkpoint(checkpoint_id)


def test_cli_enable_disable_safe_import(cli_db_path):
    runner = CliRunner()
    result = runner.invoke(cli.cli, ["enable-safe-import", cli_db_path])
    assert result.exit_code == 0
    result = runner.invoke(cli.cli, ["disable-safe-import", cli_db_path])
    assert result.exit_code == 0
