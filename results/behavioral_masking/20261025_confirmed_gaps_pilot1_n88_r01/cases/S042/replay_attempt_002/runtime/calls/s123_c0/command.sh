cd /app && python3 - <<'PY'
p='packages/core/src/query/types.ts'
s=open(p).read()
old="""type ExtractModifiersFromOrParams<T extends OrParameter[]> = T extends [infer F, ...infer R]
    ? F extends Modifier
        ? [F, ...ExtractModifiersFromOrParams<R>]
        : ExtractModifiersFromOrParams<R>
    : [];"""
new="""type ExtractModifiersFromOrParams<T extends OrParameter[]> = T extends [infer F, ...infer R]
    ? R extends OrParameter[]
        ? F extends Modifier
            ? [F, ...ExtractModifiersFromOrParams<R>]
            : ExtractModifiersFromOrParams<R>
        : []
    : [];"""
assert old in s
s=s.replace(old,new)
open(p,'w').write(s)

p='packages/core/src/query/modifiers/or.ts'
s=open(p).read()
s=s.replace("    modifier.modifiers = modifiers;", "    modifier.modifiers = modifiers as typeof modifier.modifiers;")
open(p,'w').write(s)
print('fixed')
PY
ls packages/core/tests | grep zz || true
cd packages/core && pnpm exec tsc --noEmit -p tsconfig.json 2>&1 | head -40