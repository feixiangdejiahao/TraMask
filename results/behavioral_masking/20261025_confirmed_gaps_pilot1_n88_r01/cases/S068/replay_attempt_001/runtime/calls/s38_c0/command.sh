cd /app && python3 - <<'PYEOF'
import re
path = 'sqlite_utils/db.py'
src = open(path).read()

# 1. Add csv import after contextlib import
src = src.replace('import contextlib\n', 'import contextlib\nimport csv as csv_module\n', 1)

# 2. Add exception classes after BadMultiValues class
anchor = '''class BadMultiValues(Exception):
    "With multi=True code must return a Python dictionary"

    def __init__(self, values: object) -> None:
        self.values = values
'''
addition = anchor + '''

class SafeImportNotEnabledError(Exception):
    "Safe import mode is not enabled"


class CheckpointNotFoundError(Exception):
    "Checkpoint does not exist"


class CheckpointNotActiveError(Exception):
    "Checkpoint is no longer active"


class ImportInvariantError(Exception):
    "Import invariant validation failed"
'''
assert anchor in src
src = src.replace(anchor, addition, 1)

# 3. Add invariant table constant after _COUNTS_TABLE_CREATE_SQL
anchor2 = '''_COUNTS_TABLE_CREATE_SQL = """
CREATE TABLE IF NOT EXISTS "{}"(
   "table" TEXT PRIMARY KEY,
   count INTEGER DEFAULT 0
);
""".strip()
'''
addition2 = anchor2 + '''

_IMPORT_INVARIANTS_TABLE = "_import_invariants"

_IMPORT_INVARIANTS_TABLE_CREATE_SQL = """
CREATE TABLE IF NOT EXISTS "{}"(
   "table" TEXT NOT NULL,
   id TEXT PRIMARY KEY,
   expression TEXT NOT NULL
);
""".strip()
'''
assert anchor2 in src
src = src.replace(anchor2, addition2, 1)

open(path, 'w').write(src)
print("done")
PYEOF
grep -n "csv_module\|SafeImportNotEnabledError\|_IMPORT_INVARIANTS_TABLE" sqlite_utils/db.py | head