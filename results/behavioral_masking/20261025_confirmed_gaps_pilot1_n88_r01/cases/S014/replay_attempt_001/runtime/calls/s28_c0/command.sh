cd /app && python3 - <<'PY'
p='packages/core/src/prompts/autocomplete.ts'
s=open(p).read()
s=s.replace(
"function isThenable<T>(value: T[] | Promise<T[]> | Thenable<T[]>): value is Promise<T[]> {",
"function isThenable<T>(value: T[] | Promise<T[]>): value is Promise<T[]> {")
s=s.replace("\t#fetchStartTime = 0;\n","")
s=s.replace(
"const options = this.#resolver.call(this, search, { signal: controller.signal });\n\t\t\tthis.#abortController = undefined;",
"const options = this.#resolver.call(this, search, { signal: controller.signal }) as T[];\n\t\t\tthis.#abortController = undefined;")
s=s.replace(
"this.#handleFetchFailure(id, search, err as Error, startTime);\n\t\t\treturn;",
"this.#handleFetchFailure(id, search, err as Error);\n\t\t\treturn;")
s=s.replace(
"(err) => this.#handleFetchFailure(id, search, err as Error, startTime)",
"(err) => this.#handleFetchFailure(id, search, err as Error)")
s=s.replace(
"\t#handleFetchFailure(id: number, search: string, err: Error, startTime: number): void {",
"\t#handleFetchFailure(id: number, search: string, err: Error): void {")
open(p,'w').write(s)
print("done")
PY
npx tsc --noEmit -p packages/core/tsconfig.json 2>&1 | grep -v "npm warn" | head -50