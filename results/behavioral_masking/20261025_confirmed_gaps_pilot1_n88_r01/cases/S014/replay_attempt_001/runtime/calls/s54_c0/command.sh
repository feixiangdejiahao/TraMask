cd /app && python3 - <<'PY'
p='packages/core/src/prompts/autocomplete.ts'
s=open(p).read()

# Pass startTime to failure handler
old = "this.#handleFetchFailure(id, search, err as Error);\n\t\t\treturn;"
new = "this.#handleFetchFailure(id, search, err as Error, startTime);\n\t\t\treturn;"
assert old in s
s=s.replace(old,new)

old = "(err) => this.#handleFetchFailure(id, search, err as Error)"
new = "(err) => this.#handleFetchFailure(id, search, err as Error, startTime)"
assert old in s
s=s.replace(old,new)

old = "\t#handleFetchFailure(id: number, search: string, err: Error): void {"
new = "\t#handleFetchFailure(id: number, search: string, err: Error, startTime: number): void {"
assert old in s
s=s.replace(old,new)

# Replace failure body with min-duration deferral
old = '''\t\tif (err?.name === 'AbortError') {
\t\t\tthis.loading = false;
\t\t\treturn;
\t\t}

\t\tthis.loadError = err instanceof Error ? err.message : String(err);
\t\tthis.retryCount += 1;

\t\tif (this.retryCount <= this.#maxRetries) {
\t\t\tconst delay = this.#getRetryDelay(this.retryCount);
\t\t\tthis.#clearRetryTimer();
\t\t\tthis.#retryTimer = setTimeout(() => {
\t\t\t\tthis.#retryTimer = undefined;
\t\t\t\tthis.#startFetch(search);
\t\t\t}, delay);
\t\t\t// Loading stays true while retrying.
\t\t\treturn;
\t\t}

\t\tthis.loading = false;
\t\tif (this.#fallbackOptions) {
\t\t\tthis.#options = [...this.#fallbackOptions];
\t\t\tthis.filteredOptions = [...this.#fallbackOptions];
\t\t} else {
\t\t\tthis.filteredOptions = [];
\t\t}
\t\tthis.#updateCursorAndSelection();
\t\tthis.#renderIfActive();
\t}'''
new = '''\t\tconst apply = () => {
\t\t\tif (id !== this.#fetchId || search !== this.#lastUserInput) {
\t\t\t\treturn;
\t\t\t}

\t\t\tif (err?.name === 'AbortError') {
\t\t\t\tthis.loading = false;
\t\t\t\treturn;
\t\t\t}

\t\t\tthis.loadError = err instanceof Error ? err.message : String(err);
\t\t\tthis.retryCount += 1;

\t\t\tif (this.retryCount <= this.#maxRetries) {
\t\t\t\tconst delay = this.#getRetryDelay(this.retryCount);
\t\t\t\tthis.#clearRetryTimer();
\t\t\t\tthis.#retryTimer = setTimeout(() => {
\t\t\t\t\tthis.#retryTimer = undefined;
\t\t\t\t\tthis.#startFetch(search);
\t\t\t\t}, delay);
\t\t\t\t// Loading stays true while retrying.
\t\t\t\treturn;
\t\t\t}

\t\t\tthis.loading = false;
\t\t\tif (this.#fallbackOptions) {
\t\t\t\tthis.#options = [...this.#fallbackOptions];
\t\t\t\tthis.filteredOptions = [...this.#fallbackOptions];
\t\t\t} else {
\t\t\t\tthis.filteredOptions = [];
\t\t\t}
\t\t\tthis.#updateCursorAndSelection();
\t\t\tthis.#renderIfActive();
\t\t};

\t\tif (this.#loadingMinDuration > 0) {
\t\t\tconst remaining = this.#loadingMinDuration - (Date.now() - startTime);
\t\t\tif (remaining > 0) {
\t\t\t\tthis.#clearMinDurationTimer();
\t\t\t\tthis.#minDurationTimer = setTimeout(apply, remaining);
\t\t\t\treturn;
\t\t\t}
\t\t}
\t\tapply();
\t}'''
assert old in s, "failure body not found"
s=s.replace(old,new)

open(p,'w').write(s)
print("done")
PY
cd /app && npx tsc --noEmit 2>&1 | grep -v "npm warn" | head