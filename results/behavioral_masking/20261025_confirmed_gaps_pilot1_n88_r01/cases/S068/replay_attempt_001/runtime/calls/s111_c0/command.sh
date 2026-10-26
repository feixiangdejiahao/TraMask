cd /app && cat >> tests/test_safe_import.py <<'EOF'


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
EOF
cd /app && python3 -m pytest tests/test_safe_import.py -q 2>&1 | tail -3