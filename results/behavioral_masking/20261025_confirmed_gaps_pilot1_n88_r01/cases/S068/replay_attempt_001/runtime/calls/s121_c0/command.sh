cd /app && python3 - <<'PYEOF'
path = 'docs/cli-reference.rst'
src = open(path).read()

block = '''
.. _cli_ref_enable_safe_import:

enable-safe-import
==================

:ref:`Safe imports <cli_safe_import>`.

::

    Usage: sqlite-utils enable-safe-import [OPTIONS] PATH

      Enable safe import mode for a database

    Options:
      --load-extension TEXT  Path to SQLite extension, with optional :entrypoint
      -h, --help             Show this message and exit.


.. _cli_ref_disable_safe_import:

disable-safe-import
===================

:ref:`Safe imports <cli_safe_import>`.

::

    Usage: sqlite-utils disable-safe-import [OPTIONS] PATH

      Disable safe import mode for a database

    Options:
      --load-extension TEXT  Path to SQLite extension, with optional :entrypoint
      -h, --help             Show this message and exit.


.. _cli_ref_add_import_invariant:

add-import-invariant
====================

:ref:`Safe imports <cli_safe_import>`.

::

    Usage: sqlite-utils add-import-invariant [OPTIONS] PATH TABLE SQL

      Add an import invariant to a table

    Options:
      --load-extension TEXT  Path to SQLite extension, with optional :entrypoint
      -h, --help             Show this message and exit.


.. _cli_ref_remove_import_invariant:

remove-import-invariant
=======================

:ref:`Safe imports <cli_safe_import>`.

::

    Usage: sqlite-utils remove-import-invariant [OPTIONS] PATH TABLE
                                               INVARIANT_ID

      Remove an import invariant from a table

    Options:
      --load-extension TEXT  Path to SQLite extension, with optional :entrypoint
      -h, --help             Show this message and exit.


.. _cli_ref_list_import_invariants:

list-import-invariants
======================

:ref:`Safe imports <cli_safe_import>`.

::

    Usage: sqlite-utils list-import-invariants [OPTIONS] PATH TABLE

      List import invariants for a table

    Options:
      --load-extension TEXT  Path to SQLite extension, with optional :entrypoint
      -h, --help             Show this message and exit.


.. _cli_ref_validate_import_invariants:

validate-import-invariants
==========================

:ref:`Safe imports <cli_safe_import>`.

::

    Usage: sqlite-utils validate-import-invariants [OPTIONS] PATH TABLE

      Validate import invariants for a table

    Options:
      --load-extension TEXT  Path to SQLite extension, with optional :entrypoint
      -h, --help             Show this message and exit.


.. [[[end]]]
'''
old = '\n\n.. [[[end]]]\n'
assert old in src
src = src.replace(old, block, 1)
open(path, 'w').write(src)
print("done")
PYEOF
cd /app && python3 -m pytest tests/test_docs.py -q 2>&1 | tail -3