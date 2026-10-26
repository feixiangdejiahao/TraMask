cd /app && python3 - <<'PY'
p='packages/core/test/prompts/async-autocomplete.test.ts'
s=open(p).read()
old = '''\ttest('exhausted retries set loadError and fallbackOptions shown', async () => {
\t\tvi.useFakeTimers();
\t\tlet calls = 0;
\t\tconst resolver = async () => {
\t\t\tcalls++;
\t\t\tthrow new Error('boom');
\t\t};'''
new = '''\ttest('exhausted retries set loadError and fallbackOptions shown', async () => {
\t\tvi.useFakeTimers();
\t\tconst resolver = async () => {
\t\t\tthrow new Error('boom');
\t\t};'''
assert old in s
s=s.replace(old,new)
open(p,'w').write(s)
print("done")
PY
npx biome check packages/core/test/prompts/async-autocomplete.test.ts packages/prompts/test/async-autocomplete.test.ts 2>&1 | tail -4