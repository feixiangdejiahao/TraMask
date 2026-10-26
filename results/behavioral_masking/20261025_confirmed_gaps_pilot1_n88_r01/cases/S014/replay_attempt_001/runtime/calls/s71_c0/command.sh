cd /app && python3 - <<'PY'
p='packages/core/src/prompts/autocomplete.ts'
s=open(p).read()

old = '''\t\t\tthis.searchTooShort = false;

\t\t\tif (this.#cacheResults) {'''
new = '''\t\t\tthis.searchTooShort = false;
\t\t\tthis.loadError = undefined;
\t\t\tthis.retryCount = 0;

\t\t\tif (this.#cacheResults) {'''
assert old in s
s=s.replace(old,new)

old = '''\t#scheduleDebouncedFetch(search: string): void {
\t\tthis.#clearDebounceTimer();
\t\tthis.#debounceTimer = setTimeout(() => {'''
new = '''\t#scheduleDebouncedFetch(search: string): void {
\t\tthis.#clearDebounceTimer();
\t\tthis.#clearMinDurationTimer();
\t\tthis.#clearRetryTimer();
\t\tthis.#debounceTimer = setTimeout(() => {'''
assert old in s
s=s.replace(old,new)

open(p,'w').write(s)
print("done")
PY
cd /app && npx tsc --noEmit 2>&1 | grep -v "npm warn" | head