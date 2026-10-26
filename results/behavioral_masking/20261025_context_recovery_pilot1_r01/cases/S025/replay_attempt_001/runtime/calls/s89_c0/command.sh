cd /app && python3 - <<'PY'
p='packages/core/src/prompts/autocomplete.ts'
s=open(p).read()
old = "\t\t\tthis.#runFetch('', { immediate: true, isInitial: true });"
new = "\t\t\tthis.#runFetch('', { immediate: true });"
assert old in s
s=s.replace(old,new)
old = """\t#runFetch(
\t\tsearch: string,
\t\topts: { immediate?: boolean; isInitial?: boolean; isRetry?: boolean } = {}
\t): void {"""
new = """\t#runFetch(
\t\tsearch: string,
\t\topts: { immediate?: boolean; isRetry?: boolean } = {}
\t): void {"""
assert old in s
s=s.replace(old,new)
open(p,'w').write(s)
print("done")
PY
cd /app && npx tsc --noEmit --project tsconfig.json 2>&1 | grep -v 'npm warn' | head -5 && cd packages/core && pnpm build 2>&1 | tail -2