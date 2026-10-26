cd /app && python3 - <<'PY'
p='packages/prompts/test/async-autocomplete.test.ts'
s=open(p).read()
s=s.replace(
"const resolver = vi.fn(async (search: string) => {\n\t\t\tconst all = [",
"const resolver = vi.fn(async (search: string, _opts: { signal: AbortSignal }) => {\n\t\t\tconst all = [")
open(p,'w').write(s)
print("done")
PY
cd /app && npx tsc --noEmit 2>&1 | grep -v "npm warn" | head