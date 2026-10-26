cd /app && python3 - <<'PYEOF'
path = 'sqlite_utils/db.py'
src = open(path).read()

# Add helper after _forget_checkpoint
old = """    def _forget_checkpoint(self, checkpoint_id: str) -> None:
        self._active_checkpoints.discard(checkpoint_id)
        if checkpoint_id in self._active_checkpoint_order:
            self._active_checkpoint_order.remove(checkpoint_id)

    def _require_active_checkpoint(self, checkpoint_id: str) -> None:
"""
new = """    def _forget_checkpoint(self, checkpoint_id: str) -> None:
        self._active_checkpoints.discard(checkpoint_id)
        if checkpoint_id in self._active_checkpoint_order:
            self._active_checkpoint_order.remove(checkpoint_id)

    def _invalidate_inner_checkpoints(self, checkpoint_id: str) -> None:
        """
        When a savepoint is released or rolled back, any savepoints created
        after it are destroyed by SQLite. Remove them from active tracking.
        """
        try:
            index = self._active_checkpoint_order.index(checkpoint_id)
        except ValueError:
            return
        for inner_id in self._active_checkpoint_order[index + 1:]:
            self._active_checkpoints.discard(inner_id)
        self._active_checkpoint_order = self._active_checkpoint_order[: index + 1]

    def _require_active_checkpoint(self, checkpoint_id: str) -> None:
"""
assert old in src
src = src.replace(old, new, 1)

# commit_checkpoint: invalidate inner before forget
old = """        self._require_active_checkpoint(checkpoint_id)
        self.execute("RELEASE SAVEPOINT {}".format(quote_identifier(checkpoint_id)))
        self._forget_checkpoint(checkpoint_id)
        self._finalized_checkpoints.add(checkpoint_id)
"""
new = """        self._require_active_checkpoint(checkpoint_id)
        self.execute("RELEASE SAVEPOINT {}".format(quote_identifier(checkpoint_id)))
        self._invalidate_inner_checkpoints(checkpoint_id)
        self._forget_checkpoint(checkpoint_id)
        self._finalized_checkpoints.add(checkpoint_id)
"""
assert old in src
src = src.replace(old, new, 1)

# rollback_to_checkpoint: use helper
old = """        self.execute("ROLLBACK TO SAVEPOINT {}".format(quoted))
        self.execute("RELEASE SAVEPOINT {}".format(quoted))
        # Any checkpoints created after this one were destroyed by the rollback
        try:
            index = self._active_checkpoint_order.index(checkpoint_id)
            for inner_id in self._active_checkpoint_order[index + 1:]:
                self._active_checkpoints.discard(inner_id)
            self._active_checkpoint_order = self._active_checkpoint_order[: index + 1]
        except ValueError:
            pass
        self._forget_checkpoint(checkpoint_id)
        self._finalized_checkpoints.add(checkpoint_id)
"""
new = """        self.execute("ROLLBACK TO SAVEPOINT {}".format(quoted))
        self.execute("RELEASE SAVEPOINT {}".format(quoted))
        # Any checkpoints created after this one were destroyed by the rollback
        self._invalidate_inner_checkpoints(checkpoint_id)
        self._forget_checkpoint(checkpoint_id)
        self._finalized_checkpoints.add(checkpoint_id)
"""
assert old in src
src = src.replace(old, new, 1)

# cleanup_checkpoint: invalidate inner before forget
old = """            self._forget_checkpoint(checkpoint_id)
        elif checkpoint_id in self._finalized_checkpoints:
"""
new = """            self._invalidate_inner_checkpoints(checkpoint_id)
            self._forget_checkpoint(checkpoint_id)
        elif checkpoint_id in self._finalized_checkpoints:
"""
assert old in src
src = src.replace(old, new, 1)

open(path, 'w').write(src)
print("done")
PYEOF
python3 -m py_compile sqlite_utils/db.py && python3 - <<'EOF'
from sqlite_utils import Database
# commit outer with active inner
db = Database(memory=True)
db.enable_safe_import()
c1 = db.create_import_checkpoint()
c2 = db.create_import_checkpoint()
db["t"].insert({"id": 1}, pk="id")
db.commit_checkpoint(c1)
try:
    db.commit_checkpoint(c2)
    print("ERROR: c2 still active")
except Exception as e:
    print("c2 after commit outer ->", type(e).__name__)
# cleanup outer with active inner
db2 = Database(memory=True)
db2.enable_safe_import()
d1 = db2.create_import_checkpoint()
d2 = db2.create_import_checkpoint()
db2.cleanup_checkpoint(d1)
try:
    db2.commit_checkpoint(d2)
    print("ERROR: d2 still active")
except Exception as e:
    print("d2 after cleanup outer ->", type(e).__name__)
EOF