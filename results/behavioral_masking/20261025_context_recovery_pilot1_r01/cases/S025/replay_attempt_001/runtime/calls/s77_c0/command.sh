cd /app && python3 - <<'PY'
p='packages/core/src/prompts/autocomplete.ts'
s=open(p).read()
old = """\t\tif (this.#cache) {
\t\t\tthis.#cache.set(search, options);
\t\t\tthis.#trimCache();
\t\t}"""
new = """\t\tif (this.#cache) {
\t\t\tthis.#cache.set(search, [...options]);
\t\t\tthis.#trimCache();
\t\t}"""
assert old in s
s=s.replace(old,new)
open(p,'w').write(s)
print("done")
PY
cd /app/packages/core && pnpm build 2>&1 | tail -2 && npx vitest run 2>&1 | tail -6 && cd /app/packages/prompts && npx vitest run 2>&1 | tail -6