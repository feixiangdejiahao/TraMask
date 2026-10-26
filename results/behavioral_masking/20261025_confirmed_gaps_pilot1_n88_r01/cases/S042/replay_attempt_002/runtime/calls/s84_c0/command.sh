cd /app && python3 - <<'PY'
p='packages/core/src/relation/tracking.ts'
s=open(p).read()
old="""export function markPairEvent(
    world: World,
    relationTrait: Trait,
    entity: Entity,
    target: Entity,
    type: 'add' | 'remove' | 'change'
) {
    const ctx = world[$internal];
    const traitId = relationTrait.id;

    for (const tracker of ctx.relationTrackers.values()) {"""
new="""export function markPairEvent(
    world: World,
    relationTrait: Trait,
    entity: Entity,
    target: Entity,
    type: 'add' | 'remove' | 'change'
): boolean {
    const ctx = world[$internal];
    const traitId = relationTrait.id;

    let canceled = false;

    for (const tracker of ctx.relationTrackers.values()) {"""
assert old in s
s=s.replace(old,new)
old2="""        if (type === 'add') {
            const removedByEntity = tracker.removed.get(traitId);
            const removedTargets = removedByEntity?.get(entity);
            if (removedTargets?.delete(target)) {
                if (removedTargets.size === 0) removedByEntity!.delete(entity);
            } else {
                targets.add(target);
            }
        } else if (type === 'remove') {
            const addedByEntity = tracker.added.get(traitId);
            const addedTargets = addedByEntity?.get(entity);
            if (addedTargets?.delete(target)) {
                if (addedTargets.size === 0) addedByEntity!.delete(entity);
            } else {
                targets.add(target);
            }
        } else {
            targets.add(target);
        }
    }
}"""
new2="""        if (type === 'add') {
            const removedByEntity = tracker.removed.get(traitId);
            const removedTargets = removedByEntity?.get(entity);
            if (removedTargets?.delete(target)) {
                canceled = true;
                if (removedTargets.size === 0) removedByEntity!.delete(entity);
            } else {
                targets.add(target);
            }
        } else if (type === 'remove') {
            const addedByEntity = tracker.added.get(traitId);
            const addedTargets = addedByEntity?.get(entity);
            if (addedTargets?.delete(target)) {
                canceled = true;
                if (addedTargets.size === 0) addedByEntity!.delete(entity);
            } else {
                targets.add(target);
            }
        } else {
            targets.add(target);
        }
    }

    return canceled;
}"""
assert old2 in s
s=s.replace(old2,new2)
# update updateQueries signature
old3="""export function updateQueriesForRelationPairChange(
    world: World,
    relationTrait: Trait,
    entity: Entity,
    target: Entity,
    eventType: 'add' | 'remove' | 'change'
) {
    const ctx = world[$internal];
    const instance = getTraitInstance(ctx.traitInstances, relationTrait);
    if (!instance) return;

    const { generationId, bitflag } = instance;

    for (const query of instance.trackingQueries) {
        const match = query.checkTracking(world, entity, eventType, generationId, bitflag, target);
        if (match) query.add(entity);
        else query.remove(world, entity);
    }
}"""
new3="""export function updateQueriesForRelationPairChange(
    world: World,
    relationTrait: Trait,
    entity: Entity,
    target: Entity,
    eventType: 'add' | 'remove' | 'change',
    canceled = false
) {
    const ctx = world[$internal];
    const instance = getTraitInstance(ctx.traitInstances, relationTrait);
    if (!instance) return;

    const { generationId, bitflag } = instance;

    for (const query of instance.trackingQueries) {
        const match = query.checkTracking(
            world,
            entity,
            eventType,
            generationId,
            bitflag,
            target,
            canceled
        );
        if (match) query.add(entity);
        else query.remove(world, entity);
    }
}"""
assert old3 in s
s=s.replace(old3,new3)
open(p,'w').write(s)
print('tracking.ts updated')
PY
grep -n "canceled\|return canceled" packages/core/src/relation/tracking.ts