cd /app && python3 - <<'PYEOF'
path = 'sqlite_utils/db.py'
src = open(path).read()

# 1. Add _safe_import_in_progress field
old = "        self._safe_import_previous_isolation_level = None\n"
new = "        self._safe_import_previous_isolation_level = None\n        self._safe_import_in_progress = False\n"
assert old in src
src = src.replace(old, new, 1)

# 2. Add _transaction context manager after ensure_autocommit_off
anchor = '''    @contextlib.contextmanager
    def tracer(
'''
addition = '''    @contextlib.contextmanager
    def _transaction(self) -> Generator[None, None, None]:
        """
        Context manager for internal transactions. During a safe import the
        context manager does nothing, so that ``with self.conn:`` blocks do not
        commit the active rollback checkpoint. Otherwise it behaves like
        ``with self.conn:``.
        """
        if getattr(self, "_safe_import_in_progress", False):
            yield
        else:
            with self.conn:
                yield

'''
assert anchor in src
src = src.replace(anchor, addition, 1)

# 3. enable/disable set _safe_import_in_progress
old = """        if not self._safe_import_enabled:
            self._safe_import_previous_isolation_level = self.conn.isolation_level
            self.conn.isolation_level = None
            self._safe_import_enabled = True
"""
new = """        if not self._safe_import_enabled:
            self._safe_import_previous_isolation_level = self.conn.isolation_level
            self.conn.isolation_level = None
            self._safe_import_enabled = True
            self._safe_import_in_progress = True
"""
assert old in src
src = src.replace(old, new, 1)

old = """        if self._safe_import_enabled:
            self.conn.isolation_level = self._safe_import_previous_isolation_level
            self._safe_import_enabled = False
"""
new = """        if self._safe_import_enabled:
            self.conn.isolation_level = self._safe_import_previous_isolation_level
            self._safe_import_enabled = False
            self._safe_import_in_progress = False
"""
assert old in src
src = src.replace(old, new, 1)

# 4. In _safe_import_operation, set _safe_import_in_progress around the op
old = """        old_isolation_level = self.conn.isolation_level
        checkpoint_id = None
        committed = False
        try:
            self.conn.isolation_level = None
            checkpoint_id = self._create_checkpoint()
"""
new = """        old_isolation_level = self.conn.isolation_level
        old_safe_import_in_progress = self._safe_import_in_progress
        checkpoint_id = None
        committed = False
        try:
            self.conn.isolation_level = None
            self._safe_import_in_progress = True
            checkpoint_id = self._create_checkpoint()
"""
assert old in src
src = src.replace(old, new, 1)

old = """        finally:
            self.conn.isolation_level = old_isolation_level

    def safe_bulk_insert(
"""
new = """        finally:
            self.conn.isolation_level = old_isolation_level
            self._safe_import_in_progress = old_safe_import_in_progress

    def safe_bulk_insert(
"""
assert old in src
src = src.replace(old, new, 1)

# 5. Fix invariant create table format (template already has quotes)
old = """            _IMPORT_INVARIANTS_TABLE_CREATE_SQL.format(
                quote_identifier(_IMPORT_INVARIANTS_TABLE)
            )
"""
new = """            _IMPORT_INVARIANTS_TABLE_CREATE_SQL.format(_IMPORT_INVARIANTS_TABLE)
"""
assert old in src
src = src.replace(old, new, 1)

# 6. Fix backslash-quoted table column names
src = src.replace('(\\"table\\", id, expression)', '("table", id, expression)')
src = src.replace('WHERE \\"table\\" = ? AND id = ?', 'WHERE "table" = ? AND id = ?')
src = src.replace('WHERE \\"table\\" = ? ORDER BY rowid', 'WHERE "table" = ? ORDER BY rowid')

# 7. Replace all internal with self.conn / self.db.conn
src = src.replace('        with self.conn:\n', '        with self._transaction():\n')
src = src.replace('            with self.conn:\n', '            with self._transaction():\n')
src = src.replace('        with self.db.conn:\n', '        with self.db._transaction():\n')
src = src.replace('            with self.db.conn:\n', '            with self.db._transaction():\n')

open(path, 'w').write(src)
print("done")
PYEOF
python3 -m py_compile sqlite_utils/db.py && grep -n "_safe_import_in_progress\|def _transaction" sqlite_utils/db.py | head