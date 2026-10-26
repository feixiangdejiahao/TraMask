cd /app && python3 - <<'PYEOF'
path = 'sqlite_utils/db.py'
src = open(path).read()

# Add helper after _forget_checkpoint
old = '''    def _forget_checkpoint(self, checkpoint_id: str) -> None:
        self._active_checkpoints.discard(checkpoint_id)
        if checkpoint_id in self._active_checkpoint_order:
            self._active_checkpoint_order.remove(checkpoint_id)

    def _require_active_checkpoint(self, checkpoint_id: str) -> None:
'''
new = '''    def _forget_checkpoint(self, checkpoint_id: str) -> None:
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
'''
assert old in src, "helper anchor"
src = src.replace(old, new, 1)

# commit_checkpoint
old = '''        self._require_active_checkpoint(checkpoint_id)
        self.execute("RELEASE SAVEPOINT {}".format(quote_identifier(checkpoint_id)))
        self._forget_checkpoint(checkpoint_id)
        self._finalized_checkpoints.add(checkpoint_id)
'''
new = '''        self._require_active_checkpoint(checkpoint_id)
        self.execute("RELEASE SAVEPOINT {}".format(quote_identifier(checkpoint_id)))
        self._invalidate_inner_checkpoints(checkpoint_id)
        self._forget_checkpoint(checkpoint_id)
        self._finalized_checkpoints.add(checkpoint_id)
'''
assert old in src, "commit anchor"
src = src.replace(old, new, 1)

# rollback_to_checkpoint: replace inline block
old = '''        self.execute("ROLLBACK TO SAVEPOINT {}".format(quoted))
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
'''
new = '''        self.execute("ROLLBACK TO SAVEPOINT {}".format(quoted))
        self.execute("RELEASE SAVEPOINT {}".format(quoted))
        # Any checkpoints created after this one were destroyed by the rollback
        self._invalidate_inner_checkpoints(checkpoint_id)
        self._forget_checkpoint(checkpoint_id)
        self._finalized_checkpoints.add(checkpoint_id)
'''
assert old in src, "rollback anchor"
src = src.replace(old, new, 1)

# cleanup_checkpoint
old = '''            except Exception:
                pass
            self._forget_checkpoint(checkpoint_id)
        elif checkpoint_id in self._finalized_checkpoints:
'''
new = '''            except Exception:
                pass
            self._invalidate_inner_checkpoints(checkpoint_id)
            self._forget_checkpoint(checkpoint_id)
        elif checkpoint_id in self._finalized_checkpoints:
'''
assert old in src, "cleanup anchor"
src = src.replace(old, new, 1)

open(path, 'w').write(src)
print("done")
PYEOF
python3 -m py_compile sqlite_utils/db.py && echo OK