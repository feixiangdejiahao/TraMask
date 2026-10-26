cd /app && cat > /tmp/test_cli_csv_safe.py <<'EOF'
from click.testing import CliRunner
from sqlite_utils import cli, Database
import os, tempfile

runner = CliRunner()
tmp = tempfile.mkdtemp()
db_path = os.path.join(tmp, "data.db")
csv_path = os.path.join(tmp, "items.csv")
open(csv_path, "w").write("id,name\n1,Cleo\n2,Marnie\n")

# create db with invariant failing
db = Database(db_path)
db.add_import_invariant("items", "COUNT(*) < 2")
# safe insert CSV with detect types should fail and rollback (table not created)
r = runner.invoke(cli.cli, ["insert", db_path, "items", csv_path, "--csv", "--safe-mode", "--pk", "id"])
print("exit:", r.exit_code)
print(r.output)
print("tables:", Database(db_path).table_names())
# now remove invariant, safe insert succeeds
db.remove_import_invariant("items", db.list_import_invariants("items")[0]["id"])
r2 = runner.invoke(cli.cli, ["insert", db_path, "items", csv_path, "--csv", "--safe-mode", "--pk", "id"])
print("exit2:", r2.exit_code, r2.output)
db2 = Database(db_path)
print("tables2:", db2.table_names())
print("rows:", list(db2["items"].rows))
print("types:", db2["items"].columns_dict)
EOF
PYTHONPATH=/app python3 /tmp/test_cli_csv_safe.py