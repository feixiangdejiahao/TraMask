cd /app && python3 - <<'PY'
p='packages/core/src/query/query.ts'
s=open(p).read()
old="""        checkTracking: (
            world: World,
            entity: Entity,
            eventType: EventType,
            generationId: number,
            bitflag: number,
            target?: Entity
        ) => checkQueryTracking(world, query, entity, eventType, generationId, bitflag, target),"""
new="""        checkTracking: (
            world: World,
            entity: Entity,
            eventType: EventType,
            generationId: number,
            bitflag: number,
            target?: Entity,
            pairCanceled = false
        ) => checkQueryTracking(world, query, entity, eventType, generationId, bitflag, target, pairCanceled),"""
assert old in s
s=s.replace(old,new)
open(p,'w').write(s)
print('query.ts updated')
PY
grep -n "pairCanceled" packages/core/src/query/query.ts