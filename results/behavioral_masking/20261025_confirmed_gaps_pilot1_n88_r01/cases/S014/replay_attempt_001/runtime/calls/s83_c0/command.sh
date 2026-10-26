cd /app && python3 - <<'PY'
p='packages/core/src/prompts/autocomplete.ts'
s=open(p).read()

old = '''\t\t\tthis.loadError = err instanceof Error ? err.message : String(err);
\t\t\tthis.retryCount += 1;

\t\t\tif (this.retryCount <= this.#maxRetries) {
\t\t\t\tconst delay = this.#getRetryDelay(this.retryCount);'''
new = '''\t\t\tthis.loadError = err instanceof Error ? err.message : String(err);

\t\t\tif (this.retryCount < this.#maxRetries) {
\t\t\t\tthis.retryCount += 1;
\t\t\t\tconst delay = this.#getRetryDelay(this.retryCount);'''
assert old in s
s=s.replace(old,new)
open(p,'w').write(s)
print("done")
PY
cd /app && npx tsc --noEmit 2>&1 | grep -v "npm warn" | head