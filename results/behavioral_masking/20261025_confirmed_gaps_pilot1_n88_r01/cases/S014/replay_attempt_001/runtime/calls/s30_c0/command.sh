cd /app && python3 - <<'PY'
p='packages/core/src/prompts/autocomplete.ts'
lines=open(p).read().split('\n')
# remove #fetchStartTime declaration
out=[]
for i,l in enumerate(lines):
    if '#fetchStartTime = 0;' in l:
        continue
    out.append(l)
lines=out
# in fetchSync, add cast
for i,l in enumerate(lines):
    if 'const options = this.#resolver.call(this, search, { signal: controller.signal });' in l:
        lines[i] = l.replace('{ signal: controller.signal });', '{ signal: controller.signal }) as T[];')
    if 'this.#fetchStartTime = startTime;' in l:
        lines[i] = ''
open(p,'w').write('\n'.join(lines))
print("done")
PY
npx tsc --noEmit -p packages/core/tsconfig.json 2>&1 | grep -v "npm warn" | head -50