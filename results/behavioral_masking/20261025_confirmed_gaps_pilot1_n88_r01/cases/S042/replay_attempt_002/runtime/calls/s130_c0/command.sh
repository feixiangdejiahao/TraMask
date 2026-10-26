cd /app && python3 - <<'PY'
p='packages/core/src/query/utils/create-query-hash.ts'
s=open(p).read()
s=s.replace("""            if (isOrWithModifiers(param)) {
                for (const nested of param.modifiers) {""", """            if (isOrWithModifiers(param)) {
                const nestedModifiers = (param as unknown as { modifiers: Modifier[] }).modifiers;
                for (const nested of nestedModifiers) {""")
s=s.replace("import { isModifier, isOrWithModifiers } from '../modifier';", "import { isModifier, isOrWithModifiers } from '../modifier';\nimport type { Modifier } from '../types';")
open(p,'w').write(s)
print('hash fixed')
PY
cd packages/core && pnpm exec tsc --noEmit -p tsconfig.json 2>&1 | head -20