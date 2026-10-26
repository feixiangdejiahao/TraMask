cd /app && python3 - <<'PY'
p='packages/core/src/query/query.ts'
s=open(p).read()
old = """        checkTracking: (
            world: World,
            entity: Entity,
            eventType: EventType,
            generationId: number,
            bitflag: number
        ) => checkQueryTracking(world, query, entity, eventType, generationId, bitflag),"""
new = """        checkTracking: (
            world: World,
            entity: Entity,
            eventType: EventType,
            generationId: number,
            bitflag: number,
            target?: Entity
        ) => checkQueryTracking(world, query, entity, eventType, generationId, bitflag, target),"""
assert old in s
s=s.replace(old,new)
open(p,'w').write(s)
print('checkTracking updated')
PY
grep -n "checkTracking:" -A 9 packages/core/src/query/query.ts