cd /app && python3 - <<'PYEOF'
path = 'sqlite_utils/db.py'
src = open(path).read()

old = '''    @contextlib.contextmanager
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
            with self._transaction():
                yield

        self, tracer: Optional[Callable[[str, Optional[Sequence]], None]] = None
'''
new = '''    @contextlib.contextmanager
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

    @contextlib.contextmanager
    def tracer(
        self, tracer: Optional[Callable[[str, Optional[Sequence]], None]] = None
'''
assert old in src, "not found"
src = src.replace(old, new, 1)
open(path, 'w').write(src)
print("fixed")
PYEOF
python3 -m py_compile sqlite_utils/db.py && echo OK && grep -n "def _transaction\|def tracer" sqlite_utils/db.py | head