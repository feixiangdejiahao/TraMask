cd /app && python3 - <<'PYEOF'
path = 'sqlite_utils/cli.py'
src = open(path).read()

# upsert signature: add safe_mode after strict in def args
old = """    load_extension,
    silent,
    strict,
):
    \"\"\"
    Upsert records based on their primary key."""
new = """    load_extension,
    silent,
    strict,
    safe_mode,
):
    \"\"\"
    Upsert records based on their primary key."""
assert old in src, "upsert sig 2"
src = src.replace(old, new, 1)

# upsert call
old = """            silent=silent,
            strict=strict,
        )
    except UnicodeDecodeError as ex:
        raise click.ClickException(UNICODE_ERROR.format(ex))


@cli.command()
@click.argument(
    \"path\",
"""
new = """            silent=silent,
            strict=strict,
            safe_mode=safe_mode,
        )
    except UnicodeDecodeError as ex:
        raise click.ClickException(UNICODE_ERROR.format(ex))


@cli.command()
@click.argument(
    \"path\",
"""
assert old in src, "upsert call 2"
src = src.replace(old, new, 1)

# bulk: add --safe-mode option
old = """@import_options
@load_extension_option
def bulk(
    path,
    sql,
    file,
    batch_size,
    functions,
    flatten,
    nl,
    csv,
    tsv,
    empty_null,
    lines,
    text,
    convert,
    imports,
    delimiter,
    quotechar,
    sniff,
    no_headers,
    encoding,
    load_extension,
):
"""
new = """@import_options
@load_extension_option
@click.option(
    \"--safe-mode\", is_flag=True, default=False, help=\"Use safe import mode with rollback checkpoints\"
)
def bulk(
    path,
    sql,
    file,
    batch_size,
    functions,
    flatten,
    nl,
    csv,
    tsv,
    empty_null,
    lines,
    text,
    convert,
    imports,
    delimiter,
    quotechar,
    sniff,
    no_headers,
    encoding,
    load_extension,
    safe_mode,
):
"""
assert old in src, "bulk sig"
src = src.replace(old, new, 1)

# bulk call
old = """            functions=functions,
        )
    except (OperationalError, sqlite3.IntegrityError) as e:
        raise click.ClickException(str(e))
"""
new = """            functions=functions,
            safe_mode=safe_mode,
        )
    except (OperationalError, sqlite3.IntegrityError) as e:
        raise click.ClickException(str(e))
"""
assert old in src, "bulk call"
src = src.replace(old, new, 1)

open(path, 'w').write(src)
print("done")
PYEOF
python3 -m py_compile sqlite_utils/cli.py && echo OK