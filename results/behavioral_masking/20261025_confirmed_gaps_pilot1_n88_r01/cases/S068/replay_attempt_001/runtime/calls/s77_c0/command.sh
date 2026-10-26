cd /app && cat > /tmp/test_cli_safe.py <<'EOF'
from click.testing import CliRunner
from sqlite_utils import cli, Database
import json, io, pathlib, tempfile, os

runner = CliRunner()
tmp = tempfile.mkdtemp()
db_path = os.path.join(tmp, "data.db")

def run(args, **kw):
    return runner.invoke(cli.cli, args, **kw)

# Setup
db = Database(db_path)
db["items"].insert_all([{"id": 1, "name": "a"}, {"id": 2, "name": "b"}], pk="id")

# enable-safe-import / add invariant
r = run(["enable-safe-import", db_path])
assert r.exit_code == 0, (r.exit_code, r.output)
r = run(["add-import-invariant", db_path, "items", "COUNT(*) < 3"])
assert r.exit_code == 0, (r.exit_code, r.output)
iid = r.output.strip()
assert iid
r = run(["list-import-invariants", db_path, "items"])
assert r.exit_code == 0
assert iid in r.output and "COUNT(*) < 3" in r.output, r.output
r = run(["validate-import-invariants", db_path, "items"])
assert r.exit_code == 0
assert "Pass" in r.output, r.output

# safe insert that violates invariant -> non-zero, no changes
r = run(["insert", db_path, "items", "-", "--pk", "id", "--safe-mode"], input=json.dumps({"id": 3, "name": "c"}))
assert r.exit_code != 0, (r.exit_code, r.output)
assert "invariant" in r.output.lower() or "valid" in r.output.lower(), r.output
assert Database(db_path)["items"].count == 2

# safe insert success
r = run(["insert", db_path, "items2", "-", "--pk", "id", "--safe-mode"], input=json.dumps({"id": 1, "name": "x"}))
assert r.exit_code == 0, (r.exit_code, r.output)
assert Database(db_path)["items2"].count == 1

# safe upsert
r = run(["upsert", db_path, "items", "-", "--pk", "id", "--safe-mode"], input=json.dumps({"id": 1, "name": "updated"}))
assert r.exit_code == 0, (r.exit_code, r.output)
assert Database(db_path)["items"].get(1)["name"] == "updated"

# safe bulk with UPDATE
r = run(["bulk", db_path, "update items set name = :name where id = :id", "-", "--nl", "--safe-mode"], input='{"id": 1, "name": "bulk_updated"}\n')
assert r.exit_code == 0, (r.exit_code, r.output)
assert Database(db_path)["items"].get(1)["name"] == "bulk_updated"

# safe bulk failure
r = run(["bulk", db_path, "insert into items (id, name) values (:id, :name)", "-", "--nl", "--safe-mode"], input='{"id": 1, "name": "dup"}\n')
assert r.exit_code != 0, (r.exit_code, r.output)

# remove invariant
r = run(["remove-import-invariant", db_path, "items", iid])
assert r.exit_code == 0
r = run(["validate-import-invariants", db_path, "items"])
assert r.exit_code == 0 and "Pass" in r.output

# disable
r = run(["disable-safe-import", db_path])
assert r.exit_code == 0

print("ALL CLI TESTS PASSED")
EOF
PYTHONPATH=/app python3 /tmp/test_cli_safe.py