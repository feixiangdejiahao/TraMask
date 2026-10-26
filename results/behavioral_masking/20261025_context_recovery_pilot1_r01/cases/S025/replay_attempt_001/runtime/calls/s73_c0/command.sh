cd /app && python3 - <<'PY'
p='packages/core/src/prompts/autocomplete.ts'
s=open(p).read()

old = """\t#onSearchChange(search: string): void {
\t\t// Non-empty searches shorter than minSearchLength are suppressed."""
new = """\t#onSearchChange(search: string): void {
\t\t// Any previous debounced search is obsolete once input changes.
\t\tthis.#cancelDebounceTimer();

\t\t// Non-empty searches shorter than minSearchLength are suppressed."""
assert old in s
s=s.replace(old,new)

old = """\t#cancelMinDurationTimer(): void {
\t\tif (this.#minDurationTimer !== undefined) {
\t\t\tclearTimeout(this.#minDurationTimer);
\t\t\tthis.#minDurationTimer = undefined;
\t\t}
\t}"""
new = """\t#cancelDebounceTimer(): void {
\t\tif (this.#debounceTimer !== undefined) {
\t\t\tclearTimeout(this.#debounceTimer);
\t\t\tthis.#debounceTimer = undefined;
\t\t}
\t}

\t#cancelMinDurationTimer(): void {
\t\tif (this.#minDurationTimer !== undefined) {
\t\t\tclearTimeout(this.#minDurationTimer);
\t\t\tthis.#minDurationTimer = undefined;
\t\t}
\t}"""
assert old in s
s=s.replace(old,new)

old = """\t\tif (this.#debounceTimer !== undefined) {
\t\t\tclearTimeout(this.#debounceTimer);
\t\t\tthis.#debounceTimer = undefined;
\t\t}
\t\tthis.loading = false;"""
new = """\t\tthis.#cancelDebounceTimer();
\t\tthis.loading = false;"""
assert old in s
s=s.replace(old,new)

open(p,'w').write(s)
print("done")
PY
cd /app/packages/core && npx tsc --noEmit --project ../../tsconfig.json 2>&1 | grep -v 'npm warn' | head