cd /app && python3 - <<'PYEOF'
path = 'sqlite_utils/cli.py'
src = open(path).read()

# insert signature: add safe_mode after strict
old = """    not_null,
    default,
    strict,
):
    \"\"\"
    Insert records from FILE into a table, creating the table if it
"""
new = """    not_null,
    default,
    strict,
    safe_mode,
):
    \"\"\"
    Insert records from FILE into a table, creating the table if it
"""
assert old in src
src = src.replace(old, new, 1)

# insert call: add safe_mode=safe_mode
old = """            not_null=not_null,
            default=default,
            strict=strict,
        )
    except UnicodeDecodeError as ex:
        raise click.ClickException(UNICODE_ERROR.format(ex))


@cli.command()
@insert_upsert_options(require_pk=True)
def upsert(
"""
new = """            not_null=not_null,
            default=default,
            strict=strict,
            safe_mode=safe_mode,
        )
    except UnicodeDecodeError as ex:
        raise click.ClickException(UNICODE_ERROR.format(ex))


@cli.command()
@insert_upsert_options(require_pk=True)
def upsert(
"""
assert old in src
src = src.replace(old, new, 1)

open(path, 'w').write(src)
print("done")
PYEOF
nl -ba sqlite_utils/cli.py | sed -n '1366,1460p'