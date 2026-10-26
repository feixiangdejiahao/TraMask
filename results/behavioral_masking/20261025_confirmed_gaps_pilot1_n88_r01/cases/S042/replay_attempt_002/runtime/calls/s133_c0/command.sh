cd /app && python3 - <<'PY'
p='packages/core/src/query/query.ts'
s=open(p).read()
s=s.replace("import type { Relation, RelationPair } from '../relation/types';", "import type { Relation } from '../relation/types';")
open(p,'w').write(s)

p='packages/core/src/query/modifier.ts'
s=open(p).read()
s=s.replace("import { isRelation, isRelationPair } from '../relation/utils/is-relation';\n", "")
open(p,'w').write(s)

p='packages/core/src/query/utils/check-query-tracking.ts'
s=open(p).read()
s=s.replace("import type { Trait } from '../../trait/types';\n", "")
open(p,'w').write(s)

p='packages/core/tests/pair-tracking-modifiers.test.ts'
s=open(p).read()
s=s.replace("""        const parentA = world.spawn();
        const parentB = world.spawn();
        const childA = world.spawn(Likes(parentA));
        const childB = world.spawn(Likes(parentB));

        childA.set(Likes(parentA), { amount: 1 });""", """        const parentA = world.spawn();
        const parentB = world.spawn();
        const childA = world.spawn(Likes(parentA));
        world.spawn(Likes(parentB));

        childA.set(Likes(parentA), { amount: 1 });""")
open(p,'w').write(s)
print('cleaned')
PY
cd packages/core && pnpm exec oxlint src tests/pair-tracking-modifiers.test.ts 2>&1 | tail -30