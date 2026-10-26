cd /app && python3 - <<'PY'
p='packages/core/src/relation/relation.ts'
s=open(p).read()
s=s.replace("""    const canceled = markPairEvent(world, baseTrait, entity, target, 'add');
    updateQueriesForRelationPairChange(world, baseTrait, entity, target, 'add', canceled);""", """    const canceledByTracker = markPairEvent(world, baseTrait, entity, target, 'add');
    updateQueriesForRelationPairChange(world, baseTrait, entity, target, 'add', canceledByTracker);""")
s=s.replace("""        const canceled = markPairEvent(world, relationTrait, entity, target, 'remove');
        updateQueriesForRelationPairChange(world, relationTrait, entity, target, 'remove', canceled);""", """        const canceledByTracker = markPairEvent(world, relationTrait, entity, target, 'remove');
        updateQueriesForRelationPairChange(world, relationTrait, entity, target, 'remove', canceledByTracker);""")
open(p,'w').write(s)
print('relation.ts updated')
PY
grep -n "canceledByTracker" packages/core/src/relation/relation.ts