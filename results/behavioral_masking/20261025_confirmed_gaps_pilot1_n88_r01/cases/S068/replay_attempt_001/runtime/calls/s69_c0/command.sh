cd /app && python3 - <<'PYEOF'
path = 'sqlite_utils/cli.py'
src = open(path).read()

# 1. Add --safe-mode option to insert_upsert_options
old = """                click.option(
                    "--strict",
                    is_flag=True,
                    default=False,
                    help="Apply STRICT mode to created table",
                ),
            )
"""
new = """                click.option(
                    "--strict",
                    is_flag=True,
                    default=False,
                    help="Apply STRICT mode to created table",
                ),
                click.option(
                    "--safe-mode",
                    is_flag=True,
                    default=False,
                    help="Use safe import mode with rollback checkpoints",
                ),
            )
"""
assert old in src
src = src.replace(old, new, 1)

# 2. Add safe_mode param to insert_upsert_implementation
old = """    functions=None,
    strict=False,
):
    db = sqlite_utils.Database(path)
"""
new = """    functions=None,
    strict=False,
    safe_mode=False,
):
    db = sqlite_utils.Database(path)
"""
assert old in src
src = src.replace(old, new, 1)

# 3. Modify bulk_sql path
old = """        # For bulk_sql= we use cursor.executemany() instead
        if bulk_sql:
            if batch_size:
                doc_chunks = chunks(docs, batch_size)
            else:
                doc_chunks = [docs]
            for doc_chunk in doc_chunks:
                with db.conn:
                    db.conn.cursor().executemany(bulk_sql, doc_chunk)
            return
"""
new = """        # For bulk_sql= we use cursor.executemany() instead
        if bulk_sql:
            if safe_mode:
                result = db.safe_bulk_execute(
                    bulk_sql, docs, batch_size=batch_size or 0
                )
                if not result["success"]:
                    raise click.ClickException(result["error_report"])
                return
            if batch_size:
                doc_chunks = chunks(docs, batch_size)
            else:
                doc_chunks = [docs]
            for doc_chunk in doc_chunks:
                with db.conn:
                    db.conn.cursor().executemany(bulk_sql, doc_chunk)
            return
"""
assert old in src
src = src.replace(old, new, 1)

# 4. Modify insert_all path to support safe_mode
old = """        try:
            db.table(table).insert_all(
                docs, pk=pk, batch_size=batch_size, alter=alter, **extra_kwargs
            )
        except Exception as e:
"""
new = """        try:
            if safe_mode:
                def _run_safe_import():
                    db.table(table).insert_all(
                        docs,
                        pk=pk,
                        batch_size=batch_size,
                        alter=alter,
                        **extra_kwargs,
                    )
                    if tracker is not None:
                        db.table(table).transform(types=tracker.types)

                safe_result = db.safe_import(table, _run_safe_import)
                if not safe_result["success"]:
                    raise click.ClickException(safe_result["error_report"])
            else:
                db.table(table).insert_all(
                    docs, pk=pk, batch_size=batch_size, alter=alter, **extra_kwargs
                )
        except Exception as e:
"""
assert old in src
src = src.replace(old, new, 1)

# 5. Move tracker transform inside else branch (it's already after the try; need to gate)
old = """        if tracker is not None:
            db.table(table).transform(types=tracker.types)

        # Clean up open file-like objects
"""
new = """        if tracker is not None and not safe_mode:
            db.table(table).transform(types=tracker.types)

        # Clean up open file-like objects
"""
assert old in src
src = src.replace(old, new, 1)

open(path, 'w').write(src)
print("done")
PYEOF
python3 -m py_compile sqlite_utils/cli.py && echo OK