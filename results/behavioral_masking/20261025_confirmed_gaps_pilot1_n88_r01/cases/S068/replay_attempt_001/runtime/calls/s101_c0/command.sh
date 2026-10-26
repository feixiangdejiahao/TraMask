cd /app && python3 - <<'PYEOF'
path = 'docs/changelog.rst'
src = open(path).read()
anchor = '.. _v3_39:\n'
block = '''.. _v_unreleased:\n\nUnreleased\n----------\n\n- New safe import mode protects bulk imports against partial failure. Use ``--safe-mode`` with the ``insert``, ``upsert`` and ``bulk`` commands, or the Python API methods ``safe_bulk_insert()``, ``safe_bulk_upsert()``, ``import_csv(..., safe_mode=True)`` and ``import_json(..., safe_mode=True)``. Imports are wrapped in rollback checkpoints, persistent import invariants are validated after the writes, and the database is rolled back to its exact pre-operation state (including schema changes) if anything fails.\n- New Python API for managing rollback checkpoints and import invariants: ``enable_safe_import()``, ``disable_safe_import()``, ``create_import_checkpoint()``, ``commit_checkpoint()``, ``rollback_to_checkpoint()``, ``cleanup_checkpoint()``, ``add_import_invariant()``, ``remove_import_invariant()``, ``list_import_invariants()`` and ``validate_import_invariants()``.\n- New CLI commands: ``enable-safe-import``, ``disable-safe-import``, ``add-import-invariant``, ``remove-import-invariant``, ``list-import-invariants`` and ``validate-import-invariants``.\n\n'''
assert anchor in src
src = src.replace(anchor, block + anchor, 1)
open(path, 'w').write(src)
print("done")
PYEOF
python3 -m pytest tests/test_docs.py -q 2>&1 | tail -3