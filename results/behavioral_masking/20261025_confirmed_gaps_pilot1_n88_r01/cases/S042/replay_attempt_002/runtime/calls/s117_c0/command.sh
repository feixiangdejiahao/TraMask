cd /app && python3 - <<'PY'
p='packages/core/src/query/query-result.ts'
s=open(p).read()
s=s.replace("import { isModifier } from './modifier';", "import { isModifier, isOrWithModifiers } from './modifier';")
old="""        if (isModifier(param)) {
            // Skip not modifier.
            if (param.type === 'not') continue;

            const pairTraits = new Set<number>();"""
new="""        if (isModifier(param)) {
            // Skip not modifier.
            if (param.type === 'not') continue;

            // Recurse into Or modifiers so pair/trait state is resolved.
            if (isOrWithModifiers(param)) {
                for (const nested of param.modifiers) {
                    getQueryStores([nested], traits, stores, relationPairs, world);
                }
                continue;
            }

            const pairTraits = new Set<number>();"""
assert old in s
s=s.replace(old,new)
open(p,'w').write(s)
print('getQueryStores Or support added')
PY
cd packages/core && pnpm exec tsc --noEmit -p tsconfig.json 2>&1 | head -30