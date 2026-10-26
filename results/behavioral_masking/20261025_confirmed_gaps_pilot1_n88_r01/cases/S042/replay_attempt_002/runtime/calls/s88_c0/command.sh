cd /app && python3 - <<'PY'
p='packages/core/src/query/utils/check-query-tracking-with-relations.ts'
s=open(p).read()
s=s.replace("""    eventBitflag: number,
    target?: Entity
): boolean {
    // First check trait bitmasks and tracking state (fast)
    if (!checkQueryTracking(world, query, entity, eventType, eventGenerationId, eventBitflag, target)) {""", """    eventBitflag: number,
    target?: Entity,
    pairCanceled = false
): boolean {
    // First check trait bitmasks and tracking state (fast)
    if (!checkQueryTracking(world, query, entity, eventType, eventGenerationId, eventBitflag, target, pairCanceled)) {""")
open(p,'w').write(s)
print('updated')
PY
grep -n "pairCanceled" packages/core/src/query/utils/check-query-tracking-with-relations.ts