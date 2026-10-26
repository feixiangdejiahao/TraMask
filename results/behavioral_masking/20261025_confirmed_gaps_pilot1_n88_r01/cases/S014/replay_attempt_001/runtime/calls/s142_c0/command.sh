cd /app && python3 - <<'PY'
p='packages/core/src/prompts/autocomplete.ts'
s=open(p).read()

old = '''\t#startFetch(search: string): void {
\t\tthis.#clearTimers();
\t\tthis.#abortCurrentFetch();

\t\tconst id = ++this.#fetchId;'''
new = '''\t#startFetch(search: string): void {
\t\tthis.#clearTimers();
\t\tthis.#abortCurrentFetch();

\t\tconst id = ++this.#fetchId;
\t\tthis.loading = true;'''
assert old in s
s=s.replace(old,new)

old = '''\t\t\tif (this.#isAsync) {
\t\t\t\tthis.#handleFetchSuccess(id, search, result, startTime);
\t\t\t} else {
\t\t\t\tthis.#options = result;'''
new = '''\t\t\tif (this.#isAsync) {
\t\t\t\tthis.#handleFetchSuccess(id, search, result, startTime);
\t\t\t} else {
\t\t\t\tthis.loading = false;
\t\t\t\tthis.#options = result;'''
assert old in s
s=s.replace(old,new)

open(p,'w').write(s)
print("done")
PY
npx tsc --noEmit 2>&1 | grep -v "npm warn" | head