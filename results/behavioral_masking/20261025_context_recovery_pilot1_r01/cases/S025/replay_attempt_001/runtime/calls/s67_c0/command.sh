cd /app && python3 - <<'PY'
p='packages/core/src/prompts/autocomplete.ts'
s=open(p).read()

old = """\t#renderIfActive(): void {
\t\tif (this.state === 'initial') {
\t\t\treturn;
\t\t}
\t\t// Defer to a microtask so synchronous keypress handling (state transitions,
\t\t// cursor updates) completes before rendering. The base Prompt also renders
\t\t// after each keypress; if the frame is identical this is a no-op.
\t\tqueueMicrotask(() => {
\t\t\tif (this.state !== 'initial') {
\t\t\t\tthis.render();
\t\t\t}
\t\t});
\t}"""
new = """\t#renderIfActive(): void {
\t\t// Only render while the prompt is active; never during construction or
\t\t// while the base Prompt is still transitioning out of an error state.
\t\tif (this.state === 'active') {
\t\t\tthis.render();
\t\t}
\t}"""
assert old in s
s=s.replace(old,new)

# Fix sync throw handling in #onSearchChange
old = """\t\t\tlet result: T[] | Promise<T[]>;
\t\t\ttry {
\t\t\t\tresult = this.#callSource(search, new AbortController().signal);
\t\t\t} catch (error) {
\t\t\t\tthis.#handleFetchError(error as Error, search, this.#fetchId + 1);
\t\t\t\treturn;
\t\t\t}"""
new = """\t\t\tlet result: T[] | Promise<T[]>;
\t\t\ttry {
\t\t\t\tresult = this.#callSource(search, new AbortController().signal);
\t\t\t} catch (error) {
\t\t\t\tthis.#handleSyncError(error as Error);
\t\t\t\treturn;
\t\t\t}"""
assert old in s
s=s.replace(old,new)

# Add #handleSyncError method before #applySyncSource
old = "\t#applySyncSource(source: T[], search: string): void {"
new = """\t#handleSyncError(error: Error): void {
\t\tthis.loadError = error instanceof Error ? error.message : String(error);
\t\tthis.loading = false;
\t\tthis.searchTooShort = false;
\t\tthis.filteredOptions = this.#fallbackOptions ? [...this.#fallbackOptions] : [];
\t\tthis.#options = [...this.filteredOptions];
\t\tthis.#renderIfActive();
\t}

\t#applySyncSource(source: T[], search: string): void {"""
assert old in s
s=s.replace(old,new)

open(p,'w').write(s)
print("core done")

# Update wrapper cacheResults conversion and type
p='packages/prompts/src/autocomplete.ts'
s=open(p).read()
old = "\tcacheResults?: boolean;"
new = "\tcacheResults?: boolean | { maxCacheSize: number };"
assert old in s
s=s.replace(old,new)

old = """\t\tcacheResults:
\t\t\topts.cacheResults === true
\t\t\t\t? opts.maxCacheSize !== undefined
\t\t\t\t\t? { maxCacheSize: opts.maxCacheSize }
\t\t\t\t\t: true
\t\t\t\t: undefined,"""
new = """\t\tcacheResults:
\t\t\topts.cacheResults === true
\t\t\t\t? opts.maxCacheSize !== undefined
\t\t\t\t\t? { maxCacheSize: opts.maxCacheSize }
\t\t\t\t\t: true
\t\t\t\t: typeof opts.cacheResults === 'object' && opts.cacheResults !== null
\t\t\t\t\t? opts.maxCacheSize !== undefined
\t\t\t\t\t\t? { maxCacheSize: opts.maxCacheSize }
\t\t\t\t\t\t: opts.cacheResults
\t\t\t\t\t: undefined,"""
assert old in s, "cache conversion not found"
s=s.replace(old,new)
open(p,'w').write(s)
print("wrapper done")
PY
cd /app && npx tsc --noEmit --project tsconfig.json 2>&1 | grep -v 'npm warn' | head -20