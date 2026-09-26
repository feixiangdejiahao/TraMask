"""Local, retrospective probe; run in the isolated candidate sqlite-utils venv.

The source must be the published base plus model.patch. This script imports
the real CLI and uses fresh databases; it does not install verifier tests.
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

from click.testing import CliRunner
from sqlite_utils import Database, cli


def main():
    records = []
    for entry, age in [("insert", 31), ("insert", 15), ("bulk", 31), ("bulk", 15)]:
        with tempfile.TemporaryDirectory(prefix="sqlite-combination-") as folder:
            path = str(Path(folder) / "data.db")
            db = Database(path)
            db["users"].insert({"id": 1, "age": 30}, pk="id")
            db.enable_safe_import()
            db.add_import_invariant("users", "SELECT COUNT(*) = 0 FROM users WHERE age < 18")
            before = list(db["users"].rows)
            db.close()
            if entry == "insert":
                args = ["insert", path, "users", "-", "--pk", "id", "--safe-mode"]
                data = json.dumps([{"id": 2, "age": age}])
            else:
                args = ["bulk", path, "UPDATE users SET age = :age WHERE id = :id", "-", "--nl", "--safe-mode"]
                data = json.dumps({"id": 1, "age": age}) + "\n"
            result = CliRunner().invoke(cli.cli, args, input=data)
            db = Database(path)
            after = list(db["users"].rows)
            valid_after = db.validate_import_invariants("users")["valid"]
            db.close()
            expected_reject = age < 18
            passed = ((result.exit_code != 0 and after == before) if expected_reject
                      else (result.exit_code == 0 and any(row["age"] == age for row in after)))
            records.append({"entry": entry, "age": age, "command": args,
                            "input": data, "exit_code": result.exit_code, "output": result.output,
                            "before": before, "after": after, "invariant_valid_after": valid_after,
                            "expected_reject_and_rollback": expected_reject, "passed": passed})
    print(json.dumps({"scope": "full candidate library and Click CLI; four fresh databases; manual probe",
                      "records": records}, indent=2))
    assert [r["passed"] for r in records] == [True, True, True, False]


if __name__ == "__main__":
    main()
