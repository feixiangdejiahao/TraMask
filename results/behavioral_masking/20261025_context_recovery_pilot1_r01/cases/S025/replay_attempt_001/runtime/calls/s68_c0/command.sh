cd /app && python3 - <<'PY'
p='packages/core/test/prompts/autocomplete.test.ts'
s=open(p).read()
old = "\t\tconst resolver = vi.fn((search: string) => {\n\t\t\tif (search === 'a') {"
new = "\t\tconst resolver = vi.fn((search: string, _opts: { signal: AbortSignal }) => {\n\t\t\tif (search === 'a') {"
assert old in s
s=s.replace(old,new)
open(p,'w').write(s)

p='packages/prompts/test/autocomplete.test.ts'
s=open(p).read()
old = """\tconst flush = async () => {
\t\tawait Promise.resolve();
\t\tawait Promise.resolve();
\t};

"""
assert old in s
s=s.replace(old,"")
open(p,'w').write(s)
print("done")
PY
cd /app && npx tsc --noEmit --project tsconfig.json 2>&1 | grep -v 'npm warn' | head -20