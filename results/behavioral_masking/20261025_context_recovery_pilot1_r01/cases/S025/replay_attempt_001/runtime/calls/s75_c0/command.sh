cd /app && python3 - <<'PY'
p='packages/core/src/prompts/autocomplete.ts'
s=open(p).read()
old = """\t\t\tthis.retryCount = 0;
\t\t\tthis.#options = [];
\t\t\tthis.filteredOptions = [];
\t\t\tthis.#renderIfActive();
\t\t\treturn;"""
new = """\t\t\tthis.retryCount = 0;
\t\t\tthis.#options = [];
\t\t\tthis.filteredOptions = [];
\t\t\tthis.#updateSelection();
\t\t\tthis.#renderIfActive();
\t\t\treturn;"""
assert old in s
s=s.replace(old,new)
open(p,'w').write(s)
print("done")
PY
cd /app/packages/core && pnpm build 2>&1 | tail -2 && npx vitest run test/prompts/autocomplete.test.ts 2>&1 | tail -8