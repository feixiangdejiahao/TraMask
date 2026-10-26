cd /app && python3 - <<'PYEOF'
path = 'sqlite_utils/cli.py'
src = open(path).read()

anchor = '\n\n@cli.command(name="create-database")\n'
block = '''


@cli.command(name="enable-safe-import")
@click.argument(
    "path",
    type=click.Path(exists=True, file_okay=True, dir_okay=False, allow_dash=False),
    required=True,
)
@load_extension_option
def enable_safe_import(path, load_extension):
    """Enable safe import mode for a database

    While enabled, ``create_import_checkpoint()`` can be used to create
    rollback checkpoints and bulk imports can be run atomically.

    Example:

    \\b
        sqlite-utils enable-safe-import data.db
    """
    db = sqlite_utils.Database(path)
    _register_db_for_cleanup(db)
    _load_extensions(db, load_extension)
    db.enable_safe_import()


@cli.command(name="disable-safe-import")
@click.argument(
    "path",
    type=click.Path(exists=True, file_okay=True, dir_okay=False, allow_dash=False),
    required=True,
)
@load_extension_option
def disable_safe_import(path, load_extension):
    """Disable safe import mode for a database

    Example:

    \\b
        sqlite-utils disable-safe-import data.db
    """
    db = sqlite_utils.Database(path)
    _register_db_for_cleanup(db)
    _load_extensions(db, load_extension)
    db.disable_safe_import()


@cli.command(name="add-import-invariant")
@click.argument(
    "path",
    type=click.Path(exists=True, file_okay=True, dir_okay=False, allow_dash=False),
    required=True,
)
@click.argument("table")
@click.argument("sql")
@load_extension_option
def add_import_invariant(path, table, sql, load_extension):
    """Add an import invariant to a table

    The invariant is an SQL expression, or a SELECT statement. It is
    validated after every safe-mode import.

    Example:

    \\b
        sqlite-utils add-import-invariant data.db items 'COUNT(*) > 0'
    """
    db = sqlite_utils.Database(path)
    _register_db_for_cleanup(db)
    _load_extensions(db, load_extension)
    invariant_id = db.add_import_invariant(table, sql)
    click.echo(invariant_id)


@cli.command(name="remove-import-invariant")
@click.argument(
    "path",
    type=click.Path(exists=True, file_okay=True, dir_okay=False, allow_dash=False),
    required=True,
)
@click.argument("table")
@click.argument("invariant_id")
@load_extension_option
def remove_import_invariant(path, table, invariant_id, load_extension):
    """Remove an import invariant from a table

    Example:

    \\b
        sqlite-utils remove-import-invariant data.db items inv_abc123
    """
    db = sqlite_utils.Database(path)
    _register_db_for_cleanup(db)
    _load_extensions(db, load_extension)
    db.remove_import_invariant(table, invariant_id)


@cli.command(name="list-import-invariants")
@click.argument(
    "path",
    type=click.Path(exists=True, file_okay=True, dir_okay=False, allow_dash=False),
    required=True,
)
@click.argument("table")
@load_extension_option
def list_import_invariants(path, table, load_extension):
    """List import invariants for a table

    Outputs each invariant id followed by its SQL.

    Example:

    \\b
        sqlite-utils list-import-invariants data.db items
    """
    db = sqlite_utils.Database(path)
    _register_db_for_cleanup(db)
    _load_extensions(db, load_extension)
    for invariant in db.list_import_invariants(table):
        click.echo("{}\\t{}".format(invariant["id"], invariant["expression"]))


@cli.command(name="validate-import-invariants")
@click.argument(
    "path",
    type=click.Path(exists=True, file_okay=True, dir_okay=False, allow_dash=False),
    required=True,
)
@click.argument("table")
@load_extension_option
def validate_import_invariants(path, table, load_extension):
    """Validate import invariants for a table

    Always exits 0, even if invariants fail. Output indicates pass or fail
    and lists any failing invariant ids.

    Example:

    \\b
        sqlite-utils validate-import-invariants data.db items
    """
    db = sqlite_utils.Database(path)
    _register_db_for_cleanup(db)
    _load_extensions(db, load_extension)
    result = db.validate_import_invariants(table)
    if result["valid"]:
        click.echo("Pass: all import invariants for '{}' are valid".format(table))
    else:
        click.echo("Fail: {} import invariant(s) failed for '{}'".format(len(result["failures"]), table))
        for failure in result["failures"]:
            click.echo("  {}".format(failure["id"]))
'''
assert anchor in src
src = src.replace(anchor, block + anchor, 1)
open(path, 'w').write(src)
print("done")
PYEOF
python3 -m py_compile sqlite_utils/cli.py && echo OK && python3 -c "from sqlite_utils import cli; print(sorted(cli.cli.commands.keys()))"