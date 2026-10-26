cd /app && python3 - <<'PY'
p='packages/core/test/prompts/async-autocomplete.test.ts'
s=open(p).read()
old = '''\ttest('loading is false during debounce when no fetch is in flight', async () => {
\t\tvi.useFakeTimers();
\t\tconst resolver = async (search: string) => {
\t\t\treturn search ? [] : fruits;
\t\t};'''
new = '''\ttest('loading is false during debounce when no fetch is in flight', async () => {
\t\tvi.useFakeTimers();
\t\tconst resolver = (search: string) => {
\t\t\tif (search) {
\t\t\t\treturn new Promise<typeof fruits>(() => {});
\t\t\t}
\t\t\treturn fruits;
\t\t};'''
assert old in s
s=s.replace(old,new)
open(p,'w').write(s)
print("done")
PY
cd /app/packages/core && npx vitest run test/prompts/async-autocomplete.test.ts 2>&1 | tail -6