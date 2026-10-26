cd /app && python3 - <<'PY'
p='packages/core/src/relation/relation.ts'
s=open(p).read()
# add imports
s=s.replace("import type { Relation, RelationPair, RelationTarget } from './types';", "import { markPairEvent, updateQueriesForRelationPairChange } from './tracking';\nimport type { Relation, RelationPair, RelationTarget } from './types';")
# add event in addRelationTarget before updateQueriesForRelationChange
s=s.replace("""    updateQueriesForRelationChange(world, relation, entity);

    return targetIndex;""", """    // Pair-level tracking events
    markPairEvent(world, baseTrait, entity, target, 'add');
    updateQueriesForRelationPairChange(world, baseTrait, entity, target, 'add');

    updateQueriesForRelationChange(world, relation, entity);

    return targetIndex;""")
# add event in removeRelationTarget before updateQueriesForRelationChange
s=s.replace("""    if (removedIndex !== -1) {
        updateQueriesForRelationChange(world, relation, entity);
    }""", """    if (removedIndex !== -1) {
        // Pair-level tracking events
        markPairEvent(world, relationTrait, entity, target, 'remove');
        updateQueriesForRelationPairChange(world, relationTrait, entity, target, 'remove');

        updateQueriesForRelationChange(world, relation, entity);
    }""")
open(p,'w').write(s)
print('relation updated')
PY
grep -n "markPairEvent\|updateQueriesForRelationPairChange\|import" packages/core/src/relation/relation.ts | head -20