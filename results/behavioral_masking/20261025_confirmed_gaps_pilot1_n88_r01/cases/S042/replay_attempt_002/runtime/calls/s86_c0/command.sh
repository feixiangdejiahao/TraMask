cd /app && python3 - <<'PY'
p='packages/core/src/query/types.ts'
s=open(p).read()
old="""    checkTracking: (
        world: World,
        entity: Entity,
        eventType: 'add' | 'remove' | 'change',
        generationId: number,
        bitflag: number,
        target?: Entity
    ) => boolean;"""
new="""    checkTracking: (
        world: World,
        entity: Entity,
        eventType: 'add' | 'remove' | 'change',
        generationId: number,
        bitflag: number,
        target?: Entity,
        pairCanceled?: boolean
    ) => boolean;"""
assert old in s
s=s.replace(old,new)
open(p,'w').write(s)
print('types updated')
PY
grep -n "pairCanceled" packages/core/src/query/types.ts