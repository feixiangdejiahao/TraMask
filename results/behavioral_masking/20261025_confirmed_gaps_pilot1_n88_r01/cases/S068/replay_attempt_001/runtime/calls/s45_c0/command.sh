cd /app && python3 - <<'PYEOF'
path = 'sqlite_utils/db.py'
src = open(path).read()

block = '''
    def enable_safe_import(self) -> None:
        """
        Enable safe import mode for this database. While enabled the
        connection runs in autocommit mode and :meth:`create_import_checkpoint`
        can be used to create rollback checkpoints.
        """
        if not self._safe_import_enabled:
            self._safe_import_previous_isolation_level = self.conn.isolation_level
            self.conn.isolation_level = None
            self._safe_import_enabled = True

    def disable_safe_import(self) -> None:
        """
        Disable safe import mode for this database, restoring the previous
        transaction behaviour.
        """
        if self._safe_import_enabled:
            self.conn.isolation_level = self._safe_import_previous_isolation_level
            self._safe_import_enabled = False

    def _create_checkpoint(self) -> str:
        checkpoint_id = "sp_" + secrets.token_hex(16)
        self.execute(
            "SAVEPOINT {}".format(quote_identifier(checkpoint_id))
        )
        self._active_checkpoints.add(checkpoint_id)
        return checkpoint_id

    def create_import_checkpoint(self) -> str:
        """
        Create a rollback checkpoint and return its checkpoint id. The id is
        an opaque non-empty string.

        Raises :class:`SafeImportNotEnabledError` if safe import mode is not
        currently enabled.
        """
        if not self._safe_import_enabled:
            raise SafeImportNotEnabledError(
                "Safe import mode is not enabled - call enable_safe_import() first"
            )
        return self._create_checkpoint()

    def _require_active_checkpoint(self, checkpoint_id: str) -> None:
        if checkpoint_id in self._active_checkpoints:
            return
        if checkpoint_id in self._finalized_checkpoints:
            raise CheckpointNotActiveError(
                "Checkpoint {} is no longer active".format(checkpoint_id)
            )
        raise CheckpointNotFoundError(
            "Checkpoint {} does not exist".format(checkpoint_id)
        )

    def commit_checkpoint(self, checkpoint_id: str) -> None:
        """
        Commit a checkpoint created using :meth:`create_import_checkpoint`.
        Any changes made since the checkpoint was created are kept.

        Committing finalizes the checkpoint: further commit or rollback calls
        with the same id will raise :class:`CheckpointNotActiveError`.
        """
        self._require_active_checkpoint(checkpoint_id)
        self.execute("RELEASE SAVEPOINT {}".format(quote_identifier(checkpoint_id)))
        self._active_checkpoints.discard(checkpoint_id)
        self._finalized_checkpoints.add(checkpoint_id)

    def rollback_to_checkpoint(self, checkpoint_id: str) -> None:
        """
        Roll back to a checkpoint created using :meth:`create_import_checkpoint`,
        restoring the exact database state (including schema changes) from when
        the checkpoint was created.

        Rolling back finalizes the checkpoint: further commit or rollback calls
        with the same id will raise :class:`CheckpointNotActiveError`.
        """
        self._require_active_checkpoint(checkpoint_id)
        quoted = quote_identifier(checkpoint_id)
        self.execute("ROLLBACK TO SAVEPOINT {}".format(quoted))
        self.execute("RELEASE SAVEPOINT {}".format(quoted))
        self._active_checkpoints.discard(checkpoint_id)
        self._finalized_checkpoints.add(checkpoint_id)

    def cleanup_checkpoint(self, checkpoint_id: str) -> None:
        """
        Remove a checkpoint id from tracking. Active checkpoints are released
        (their changes are kept) and finalized checkpoints are simply forgotten.

        After cleanup, commit/rollback calls with the same id raise
        :class:`CheckpointNotFoundError`.
        """
        if checkpoint_id in self._active_checkpoints:
            try:
                self.execute(
                    "RELEASE SAVEPOINT {}".format(quote_identifier(checkpoint_id))
                )
            except Exception:
                pass
            self._active_checkpoints.discard(checkpoint_id)
        elif checkpoint_id in self._finalized_checkpoints:
            self._finalized_checkpoints.discard(checkpoint_id)
        else:
            raise CheckpointNotFoundError(
                "Checkpoint {} does not exist".format(checkpoint_id)
            )

    def _ensure_import_invariants_table(self) -> None:
        self.execute(
            _IMPORT_INVARIANTS_TABLE_CREATE_SQL.format(
                quote_identifier(_IMPORT_INVARIANTS_TABLE)
            )
        )

    def add_import_invariant(self, table: str, sql: str) -> str:
        """
        Add a persistent import invariant for a table. Returns an opaque
        invariant id.

        :param table: Name of the table the invariant applies to
        :param sql: SQL invariant expression, or a ``SELECT`` statement
        """
        self._ensure_import_invariants_table()
        invariant_id = "inv_" + secrets.token_hex(16)
        with self.conn:
            self.execute(
                "INSERT INTO {} (\\"table\\", id, expression) VALUES (?, ?, ?)".format(
                    quote_identifier(_IMPORT_INVARIANTS_TABLE)
                ),
                (table, invariant_id, sql),
            )
        return invariant_id

    def remove_import_invariant(self, table: str, invariant_id: str) -> None:
        """
        Remove an import invariant for a table.

        :param table: Name of the table
        :param invariant_id: Id returned by :meth:`add_import_invariant`
        """
        self._ensure_import_invariants_table()
        with self.conn:
            self.execute(
                "DELETE FROM {} WHERE \\"table\\" = ? AND id = ?".format(
                    quote_identifier(_IMPORT_INVARIANTS_TABLE)
                ),
                (table, invariant_id),
            )

    def list_import_invariants(self, table: str) -> List[Dict[str, str]]:
        """
        Return a list of ``{"id": invariant_id, "expression": sql}``
        dictionaries for the specified table.

        :param table: Name of the table
        """
        self._ensure_import_invariants_table()
        rows = self.execute(
            "SELECT id, expression FROM {} WHERE \\"table\\" = ? ORDER BY rowid".format(
                quote_identifier(_IMPORT_INVARIANTS_TABLE)
            ),
            (table,),
        ).fetchall()
        return [{"id": row[0], "expression": row[1]} for row in rows]

    def validate_import_invariants(self, table: str) -> Dict[str, Any]:
        """
        Validate every import invariant registered for ``table``.

        Returns ``{"valid": bool, "failures": [{"id", "expression", "error"}]}``.

        Invariants whose SQL starts with ``SELECT`` are evaluated directly and
        the first column of the first row is treated as truthy/falsy. Other SQL
        is treated as an expression: aggregate expressions are evaluated once
        for the table while non-aggregate expressions must be true for every
        row.
        """
        failures = []
        invariants = self.list_import_invariants(table)
        table_exists = self.table(table).exists()
        count = self.table(table).count if table_exists else 0
        for invariant in invariants:
            expression = invariant["expression"]
            ok = True
            try:
                if expression.lstrip().upper().startswith("SELECT"):
                    rows = self.execute(expression).fetchall()
                    ok = bool(rows and rows[0][0])
                else:
                    rows = self.execute(
                        "SELECT ({}) AS _import_invariant FROM {}".format(
                            expression, quote_identifier(table)
                        )
                    ).fetchall()
                    if count == 0:
                        # Non-aggregate expressions are vacuously true for an
                        # empty table; aggregate expressions return one row.
                        ok = bool(rows and rows[0][0]) if rows else True
                    elif len(rows) == 1:
                        ok = bool(rows[0][0])
                    else:
                        ok = all(bool(row[0]) for row in rows)
            except Exception as e:
                failures.append(
                    {
                        "id": invariant["id"],
                        "expression": expression,
                        "error": str(e),
                    }
                )
                continue
            if not ok:
                failures.append(
                    {
                        "id": invariant["id"],
                        "expression": expression,
                        "error": "expression evaluated to false",
                    }
                )
        return {"valid": not failures, "failures": failures}

    def _format_import_error_report(
        self,
        table: Optional[str],
        error: Optional[Exception],
        failures: List[Dict[str, Any]],
    ) -> str:
        bits = []
        if error is not None:
            bits.append("Import error: {}".format(error))
        if failures:
            bits.append("Import invariant validation failed for table '{}':".format(table))
            for failure in failures:
                bits.append(
                    "  {} {}: {}".format(
                        failure["id"],
                        failure["expression"],
                        failure.get("error") or "false",
                    )
                )
        return "\\n".join(bits)

    def safe_import(
        self,
        table: Optional[str],
        operation: Callable[[], None],
        strict: bool = False,
    ) -> Dict[str, Any]:
        """
        Run ``operation`` inside a rollback checkpoint. On success the
        checkpoint is committed and ``{"success": True}`` is returned. On
        failure the database is rolled back to its pre-operation state.

        If ``strict`` is ``True`` a failure raises an exception instead of
        returning a result dictionary. Invariant failures raise
        :class:`ImportInvariantError`.
        """
        return self._safe_import_operation(table, operation, strict=strict)

    def _safe_import_operation(
        self,
        table: Optional[str],
        operation: Callable[[], None],
        strict: bool = False,
    ) -> Dict[str, Any]:
        old_isolation_level = self.conn.isolation_level
        checkpoint_id = None
        committed = False
        try:
            self.conn.isolation_level = None
            checkpoint_id = self._create_checkpoint()
            error = None
            try:
                operation()
            except Exception as e:
                error = e
            failures: List[Dict[str, Any]] = []
            valid = True
            if error is None:
                try:
                    if table is not None:
                        validation = self.validate_import_invariants(table)
                        failures = validation["failures"]
                        valid = validation["valid"]
                except Exception as e:
                    error = e
            if error is None and valid:
                try:
                    self.commit_checkpoint(checkpoint_id)
                    committed = True
                    return {"success": True}
                except Exception as e:
                    error = e
            if not committed:
                try:
                    self.rollback_to_checkpoint(checkpoint_id)
                except Exception:
                    pass
            if strict:
                if error is not None:
                    raise error
                raise ImportInvariantError(
                    "Import invariant validation failed for table '{}': {}".format(
                        table, failures
                    )
                )
            return {
                "success": False,
                "checkpoint_id": checkpoint_id,
                "failures": failures,
                "error_report": self._format_import_error_report(table, error, failures),
            }
        finally:
            self.conn.isolation_level = old_isolation_level

    def safe_bulk_insert(
        self,
        table: str,
        records: Union[Iterable[Dict[str, Any]], Iterable[Sequence[Any]]],
        strict: bool = False,
        pk=DEFAULT,
        batch_size=DEFAULT,
        alter=DEFAULT,
        ignore=DEFAULT,
        replace=DEFAULT,
        truncate: bool = False,
        extracts=DEFAULT,
        conversions=DEFAULT,
        columns=DEFAULT,
        analyze: bool = False,
        hash_id=DEFAULT,
        hash_id_columns=DEFAULT,
        not_null=DEFAULT,
        defaults=DEFAULT,
        column_order=DEFAULT,
    ) -> Dict[str, Any]:
        """
        Safely insert many records into ``table`` using
        :meth:`Table.insert_all`, with rollback on failure and import
        invariant validation on success.
        """
        return self.safe_import(
            table,
            lambda: self.table(table).insert_all(
                records,
                pk=pk,
                batch_size=batch_size,
                alter=alter,
                ignore=ignore,
                replace=replace,
                truncate=truncate,
                extracts=extracts,
                conversions=conversions,
                columns=columns,
                analyze=analyze,
                hash_id=hash_id,
                hash_id_columns=hash_id_columns,
                not_null=not_null,
                defaults=defaults,
                column_order=column_order,
            ),
            strict=strict,
        )

    def safe_bulk_upsert(
        self,
        table: str,
        records: Union[Iterable[Dict[str, Any]], Iterable[Sequence[Any]]],
        pk,
        strict: bool = False,
        foreign_keys=DEFAULT,
        column_order=DEFAULT,
        not_null=DEFAULT,
        defaults=DEFAULT,
        batch_size=DEFAULT,
        hash_id=DEFAULT,
        hash_id_columns=DEFAULT,
        alter=DEFAULT,
        extracts=DEFAULT,
        conversions=DEFAULT,
        columns=DEFAULT,
        analyze: bool = False,
    ) -> Dict[str, Any]:
        """
        Safely upsert many records into ``table`` using
        :meth:`Table.upsert_all`, with rollback on failure and import
        invariant validation on success.
        """
        return self.safe_import(
            table,
            lambda: self.table(table).upsert_all(
                records,
                pk=pk,
                foreign_keys=foreign_keys,
                column_order=column_order,
                not_null=not_null,
                defaults=defaults,
                batch_size=batch_size,
                hash_id=hash_id,
                hash_id_columns=hash_id_columns,
                alter=alter,
                extracts=extracts,
                conversions=conversions,
                columns=columns,
                analyze=analyze,
            ),
            strict=strict,
        )

    def safe_bulk_execute(
        self,
        sql: str,
        records: Iterable[Any],
        batch_size: int = 100,
        strict: bool = False,
    ) -> Dict[str, Any]:
        """
        Safely execute a parameterized SQL statement against ``records`` using
        ``cursor.executemany()``, with rollback on failure.
        """
        return self.safe_import(
            None,
            lambda: self._bulk_execute(sql, records, batch_size),
            strict=strict,
        )

    def _bulk_execute(self, sql: str, records: Iterable[Any], batch_size: int) -> None:
        if batch_size:
            doc_chunks = chunks(records, batch_size)
        else:
            doc_chunks = [records]
        for doc_chunk in doc_chunks:
            self.conn.cursor().executemany(sql, doc_chunk)

    def import_csv(
        self,
        table: str,
        source,
        safe_mode: bool = False,
        strict: bool = False,
        pk=DEFAULT,
        batch_size=DEFAULT,
        alter=DEFAULT,
        delimiter: Optional[str] = None,
        quotechar: Optional[str] = None,
        no_headers: bool = False,
        encoding: str = "utf-8-sig",
        empty_null: bool = False,
        **kwargs,
    ):
        """
        Import records from a CSV file into ``table``.

        ``source`` may be a path string or a text file-like object. When
        ``safe_mode=True`` the import is atomic and validates import
        invariants.
        """
        close = False
        if isinstance(source, (str, pathlib.Path)):
            file = open(source, "r", encoding=encoding, newline="")
            close = True
        else:
            file = source
        try:
            reader = csv_module.reader(
                file,
                delimiter=delimiter or ",",
                quotechar=quotechar or '"',
            )
            first_row = next(reader)
            if no_headers:
                headers = ["untitled_{}".format(i + 1) for i in range(len(first_row))]
                reader = itertools.chain([first_row], reader)
            else:
                headers = first_row
            if empty_null:
                records = (
                    dict(
                        zip(
                            headers,
                            [None if cell == "" else cell for cell in row],
                        )
                    )
                    for row in reader
                )
            else:
                records = (dict(zip(headers, row)) for row in reader)
            if safe_mode:
                return self.safe_bulk_insert(
                    table,
                    records,
                    strict=strict,
                    pk=pk,
                    batch_size=batch_size,
                    alter=alter,
                    **kwargs,
                )
            return self.table(table).insert_all(
                records,
                pk=pk,
                batch_size=batch_size,
                alter=alter,
                **kwargs,
            )
        finally:
            if close:
                file.close()

    def import_json(
        self,
        table: str,
        data,
        safe_mode: bool = False,
        strict: bool = False,
        pk=DEFAULT,
        batch_size=DEFAULT,
        alter=DEFAULT,
        **kwargs,
    ):
        """
        Import records from a JSON list (or a JSON string) into ``table``.

        When ``safe_mode=True`` the import is atomic and validates import
        invariants.
        """
        if isinstance(data, str):
            data = json.loads(data)
        if isinstance(data, dict):
            data = [data]
        if safe_mode:
            return self.safe_bulk_insert(
                table,
                data,
                strict=strict,
                pk=pk,
                batch_size=batch_size,
                alter=alter,
                **kwargs,
            )
        return self.table(table).insert_all(
            data,
            pk=pk,
            batch_size=batch_size,
            alter=alter,
            **kwargs,
        )

'''

anchor = "    def resolve_foreign_keys(\n"
assert anchor in src
src = src.replace(anchor, block + anchor, 1)
open(path, 'w').write(src)
print("done")
PYEOF