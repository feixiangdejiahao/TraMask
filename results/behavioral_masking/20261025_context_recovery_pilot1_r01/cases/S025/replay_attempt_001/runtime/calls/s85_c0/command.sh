cd /app && python3 - <<'PY'
p='packages/core/test/prompts/autocomplete.test.ts'
s=open(p).read()
old = "\t\tsignals.push(resolver.mock.calls.at(-1)![1].signal);"
new = "\t\tconst lastCall = resolver.mock.calls.at(-1);\n\t\tif (lastCall) {\n\t\t\tsignals.push(lastCall[1].signal);\n\t\t}"
assert old in s
s=s.replace(old,new)
open(p,'w').write(s)
print("done")
PY
cd /app && pnpm exec biome check packages/core/src/prompts/autocomplete.ts packages/core/src/prompts/prompt.ts packages/prompts/src/autocomplete.ts packages/core/test/prompts/autocomplete.test.ts packages/prompts/test/autocomplete.test.ts 2>&1 | tail -10