cd /app && python3 - <<'PY'
p='packages/core/src/relation/tracking.ts'
s=open(p).read()
# Replace function body from markPairEvent start to return
start=s.index("export function markPairEvent(")
end=s.index("/**\n * Update tracking queries")
old=s[start:end]
new='''export function markPairEvent(
    world: World,
    relationTrait: Trait,
    entity: Entity,
    target: Entity,
    type: 'add' | 'remove' | 'change'
): Map<number, boolean> {
    const ctx = world[$internal];
    const traitId = relationTrait.id;
    const canceledByTracker = new Map<number, boolean>();

    for (const [trackerId, tracker] of ctx.relationTrackers) {
        const eventMap =
            type === 'add'
                ? tracker.added
                : type === 'remove'
                  ? tracker.removed
                  : tracker.changed;

        let byEntity = eventMap.get(traitId);
        if (!byEntity) {
            byEntity = new Map();
            eventMap.set(traitId, byEntity);
        }

        let targets = byEntity.get(entity);
        if (!targets) {
            targets = new Set();
            byEntity.set(entity, targets);
        }

        let canceled = false;

        if (type === 'add') {
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

        canceledByTracker.set(trackerId, canceled);
    }

    return canceledByTracker;
}

'''
s=s[:start]+new+s[end:]
# update updateQueries signature and checkTracking call
s=s.replace("""export function updateQueriesForRelationPairChange(
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
}""", """export function updateQueriesForRelationPairChange(
    world: World,
    relationTrait: Trait,
    entity: Entity,
    target: Entity,
    eventType: 'add' | 'remove' | 'change',
    canceledByTracker?: Map<number, boolean>
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
            canceledByTracker
        );
        if (match) query.add(entity);
        else query.remove(world, entity);
    }
}""")
open(p,'w').write(s)
print('tracking.ts refactored')
PY
grep -n "canceledByTracker\|Map<number, boolean>" packages/core/src/relation/tracking.ts | head -30