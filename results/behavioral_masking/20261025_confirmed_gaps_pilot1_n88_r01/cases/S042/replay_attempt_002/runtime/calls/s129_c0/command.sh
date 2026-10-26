cd /app && python3 - <<'PY'
p='packages/core/src/query/utils/create-query-hash.ts'
s=open(p).read()
s=s.replace("import { isModifier } from '../modifier';", "import { isModifier, isOrWithModifiers } from '../modifier';")
old="""        } else if (isModifier(param)) {
            const modifierId = param.id;
            const traitIds = param.traitIds;

            for (let i = 0; i < traitIds.length; i++) {
                const traitId = traitIds[i];
                sortedIDs[cursor++] = modifierId * 100000 + traitId;
            }

            // Pair-tracked modifiers must hash differently per target.
            if (param.pairs && param.pairs.length > 0) {
                for (const pair of param.pairs) {
                    const pairCtx = pair[$internal];
                    const relationTrait = pairCtx.relation[$internal].trait;
                    const target = pairCtx.target;
                    const relationId = relationTrait.id;
                    const targetId = typeof target === 'number' ? target : -1;

                    sortedIDs[cursor++] =
                        modifierId * 10000000000 +
                        relationId * 1000000 +
                        targetId +
                        500000000;
                }
            }
        } else {"""
new="""        } else if (isModifier(param)) {
            const modifierId = param.id;
            const traitIds = param.traitIds;

            for (let i = 0; i < traitIds.length; i++) {
                const traitId = traitIds[i];
                sortedIDs[cursor++] = modifierId * 100000 + traitId;
            }

            // Pair-tracked modifiers must hash differently per target.
            if (param.pairs && param.pairs.length > 0) {
                for (const pair of param.pairs) {
                    const pairCtx = pair[$internal];
                    const relationTrait = pairCtx.relation[$internal].trait;
                    const target = pairCtx.target;
                    const relationId = relationTrait.id;
                    const targetId = typeof target === 'number' ? target : -1;

                    sortedIDs[cursor++] =
                        modifierId * 10000000000 +
                        relationId * 1000000 +
                        targetId +
                        500000000;
                }
            }

            // Recurse into nested modifiers inside Or so pair targets are distinct.
            if (isOrWithModifiers(param)) {
                for (const nested of param.modifiers) {
                    const nestedId = nested.id;
                    for (const traitId of nested.traitIds) {
                        sortedIDs[cursor++] = nestedId * 100000 + traitId;
                    }
                    if (nested.pairs) {
                        for (const pair of nested.pairs) {
                            const pairCtx = pair[$internal];
                            const relationTrait = pairCtx.relation[$internal].trait;
                            const target = pairCtx.target;
                            const relationId = relationTrait.id;
                            const targetId = typeof target === 'number' ? target : -1;

                            sortedIDs[cursor++] =
                                nestedId * 10000000000 +
                                relationId * 1000000 +
                                targetId +
                                500000000;
                        }
                    }
                }
            }
        } else {"""
assert old in s
s=s.replace(old,new)
open(p,'w').write(s)
print('hash updated')
PY
cd packages/core && pnpm exec tsc --noEmit -p tsconfig.json 2>&1 | head -20