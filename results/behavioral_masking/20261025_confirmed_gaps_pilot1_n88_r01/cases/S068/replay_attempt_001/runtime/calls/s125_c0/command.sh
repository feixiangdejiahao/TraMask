cd /app && git add -A && git commit -m "Add safe import mode with rollback checkpoints and import invariants

Implement a safe import mode for bulk imports that protects against
partial failure. Imports are wrapped in SQLite savepoint checkpoints,
persistent import invariants are validated after writes, and the
database (including schema changes) is rolled back on any failure.

Python API:
- enable_safe_import()/disable_safe_import()
- create_import_checkpoint()/commit_checkpoint()/rollback_to_checkpoint()/cleanup_checkpoint()
- add_import_invariant()/remove_import_invariant()/list_import_invariants()/validate_import_invariants()
- safe_bulk_insert()/safe_bulk_upsert()/safe_bulk_execute()
- import_csv()/import_json() with safe_mode support

CLI:
- New enable-safe-import, disable-safe-import, add-import-invariant,
  remove-import-invariant, list-import-invariants, validate-import-invariants
- insert/upsert/bulk accept --safe-mode
- bulk --safe-mode supports UPDATE

Add tests and update documentation." && git log --oneline -3 && git status --short