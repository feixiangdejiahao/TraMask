cd /app && python3 - <<'PYEOF'
path = 'docs/cli.rst'
src = open(path).read()

anchor = '.. _cli_install:\n'
block = '''.. _cli_safe_import:\n\nSafe imports and import invariants\n==================================\n\nBulk imports can fail part-way through, leaving a database in an inconsistent state. ``sqlite-utils`` provides a safe import mode that wraps an import in a rollback checkpoint, validates any configured import invariants after the writes and only commits if everything succeeds.\n\nUse the ``--safe-mode`` option with ``insert``, ``upsert`` and ``bulk`` to run the operation in safe mode. If the operation succeeds the changes are committed and the command exits ``0``. If it fails (either because of a SQL error or because an import invariant is not satisfied) the database is rolled back to its exact pre-operation state - including any schema changes such as tables, columns, indexes and triggers - and the command exits with a non-zero code.\n\n.. code-block:: bash\n\n    sqlite-utils insert data.db items items.csv --csv --safe-mode\n\nYou can register persistent import invariants for a table using ``add-import-invariant``. The invariant is an SQL expression or a ``SELECT`` statement that must hold after every safe-mode import. For example, to require that the ``items`` table never ends up empty:\n\n.. code-block:: bash\n\n    sqlite-utils add-import-invariant data.db items 'COUNT(*) > 0'\n\nInvariants are stored inside the database itself. Use ``list-import-invariants`` to see them, ``remove-import-invariant`` to delete one and ``validate-import-invariants`` to check them against the current contents of the table:\n\n.. code-block:: bash\n\n    sqlite-utils list-import-invariants data.db items\n    sqlite-utils remove-import-invariant data.db items inv_abc123\n    sqlite-utils validate-import-invariants data.db items\n\nThe ``validate-import-invariants`` command always exits ``0`` - its output indicates whether the invariants passed or failed and lists any failing invariant ids.\n\nSafe import mode can be enabled and disabled for a database using:\n\n.. code-block:: bash\n\n    sqlite-utils enable-safe-import data.db\n    sqlite-utils disable-safe-import data.db\n\nWhen safe import mode is enabled the Python API's ``create_import_checkpoint()``, ``commit_checkpoint()``, ``rollback_to_checkpoint()`` and ``cleanup_checkpoint()`` methods can be used to manage rollback checkpoints directly.\n\n'''
assert anchor in src
src = src.replace(anchor, block + anchor, 1)

# Add --safe-mode mention to insert section: after "Insert records from FILE..." intro
old = """    sqlite-utils insert data.db chickens -
"""
# There are multiple; add a note in inserting data section. Let's add to the upsert and bulk notes instead.
# Add to upsert section end
old = """    ``upsert`` in sqlite-utils 1.x worked like ``insert ... --replace`` does in 2.x. See `issue #66 <https://github.com/simonw/sqlite-utils/issues/66>`__ for details of this change.
"""
new = """    ``upsert`` in sqlite-utils 1.x worked like ``insert ... --replace`` does in 2.x. See `issue #66 <https://github.com/simonw/sqlite-utils/issues/66>`__ for details of this change.

Use ``--safe-mode`` to run the upsert inside a rollback checkpoint, so the database is only committed if the operation and any configured import invariants succeed:

.. code-block:: bash

    sqlite-utils upsert data.db items items.csv --csv --pk id --safe-mode
"""
assert old in src
src = src.replace(old, new, 1)

# Add to bulk section end
old = """By default all of the SQL queries will be executed in a single transaction. To commit every 20 records, use ``--batch-size 20``.
"""
new = """By default all of the SQL queries will be executed in a single transaction. To commit every 20 records, use ``--batch-size 20``.

Use ``--safe-mode`` to run the bulk operation inside a rollback checkpoint. This works with any SQL, including ``UPDATE`` statements, and rolls the database back to its pre-operation state if the operation fails:

.. code-block:: bash

    sqlite-utils bulk data.db 'update items set name = :name where id = :id' items.csv --csv --safe-mode
"""
assert old in src
src = src.replace(old, new, 1)

open(path, 'w').write(src)
print("done")
PYEOF
cd /app && python3 -m pytest tests/test_docs.py -q 2>&1 | tail -10