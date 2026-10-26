cd /app && python3 - <<'PY'
p='packages/core/src/relation/relation.ts'
s=open(p).read()
s=s.replace("""    // Pair-level tracking events
    markPairEvent(world, baseTrait, entity, target, 'add');
    updateQueriesForRelationPairChange(world, baseTrait, entity, target, 'add');""", """    // Pair-level tracking events
    const canceled = markPairEvent(world, baseTrait, entity, target, 'add');
    updateQueriesForRelationPairChange(world, baseTrait, entity, target, 'add', canceled);""")
s=s.replace("""        // Pair-level tracking events
        markPairEvent(world, relationTrait, entity, target, 'remove');
        updateQueriesForRelationPairChange(world, relationTrait, entity, target, 'remove');""", """        // Pair-level tracking events
        const canceled = markPairEvent(world, relationTrait, entity, target, 'remove');
        updateQueriesForRelationPairChange(world, relationTrait, entity, target, 'remove', canceled);""")
open(p,'w').write(s)
print('relation.ts updated')
PY
grep -n "canceled" packages/core/src/relation/relation.ts