cd /app && python3 - <<'PY'
p='packages/core/src/query/modifiers/changed.ts'
s=open(p).read()
s=s.replace("""    // Mark pair-level change and update pair tracking queries.
    markPairEvent(world, trait, entity, target, 'change');
    updateQueriesForRelationPairChange(world, trait, entity, target, 'change');""", """    // Mark pair-level change and update pair tracking queries.
    const canceledByTracker = markPairEvent(world, trait, entity, target, 'change');
    updateQueriesForRelationPairChange(world, trait, entity, target, 'change', canceledByTracker);""")
open(p,'w').write(s)
print('changed.ts fixed')
PY
grep -n "canceledByTracker" packages/core/src/query/modifiers/changed.ts