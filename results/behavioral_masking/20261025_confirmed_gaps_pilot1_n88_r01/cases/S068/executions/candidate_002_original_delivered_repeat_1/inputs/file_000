from click.testing import CliRunner
import pytest
from sqlite_utils import Database, cli


@pytest.fixture
def cli_db_path(tmpdir):
    from sqlite_utils.utils import sqlite3
    path = str(tmpdir / "data.db")
    db = sqlite3.connect(path)
    db.execute("create table items (id integer primary key, name text)")
    db.commit()
    db.close()
    return path



def test_cli_enable_disable_safe_import(cli_db_path):
    runner = CliRunner()
    result = runner.invoke(cli.cli, ["enable-safe-import", cli_db_path])
    assert result.exit_code == 0
    result = runner.invoke(cli.cli, ["disable-safe-import", cli_db_path])
    assert result.exit_code == 0
