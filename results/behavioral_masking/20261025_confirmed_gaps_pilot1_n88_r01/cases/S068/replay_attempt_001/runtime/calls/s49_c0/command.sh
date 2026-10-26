cd /app && python3 - <<'EOF'
import sqlite_utils
from sqlite_utils.db import _IMPORT_INVARIANTS_TABLE_CREATE_SQL, quote_identifier, _IMPORT_INVARIANTS_TABLE
sql = _IMPORT_INVARIANTS_TABLE_CREATE_SQL.format(quote_identifier(_IMPORT_INVARIANTS_TABLE))
print(repr(sql))
db = sqlite_utils.Database(memory=True)
try:
    db.execute(sql)
    print("create ok")
except Exception as e:
    print("create err:", e)
EOF