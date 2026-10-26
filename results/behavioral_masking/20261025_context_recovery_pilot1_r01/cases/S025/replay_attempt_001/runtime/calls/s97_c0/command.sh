cd /app && python3 - <<'PY'
p='packages/core/src/prompts/autocomplete.ts'
s=open(p).read()

old = """\t#onSearchChange(search: string): void {
\t\t// Any previous debounced search is obsolete once input changes.
\t\tthis.#cancelDebounceTimer();

\t\t// Non-empty searches shorter than minSearchLength are suppressed."""
new = """\t#onSearchChange(search: string): void {
\t\t// Any previous async work is obsolete once input changes.
\t\tthis.#cancelDebounceTimer();
\t\tthis.#cancelRetryTimer();
\t\tthis.#cancelMinDurationTimer();
\t\tthis.#invalidateFetch();
\t\tthis.loading = false;

\t\t// Non-empty searches shorter than minSearchLength are suppressed."""
assert old in s
s=s.replace(old,new)

open(p,'w').write(s)
print("done")
PY
cd /app && npx tsc --noEmit --project tsconfig.json 2>&1 | grep -v 'npm warn' | head -5