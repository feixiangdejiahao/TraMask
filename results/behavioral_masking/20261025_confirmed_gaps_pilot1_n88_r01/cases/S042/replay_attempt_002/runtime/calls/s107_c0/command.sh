cd /app && cat > packages/core/src/relation/tracking.ts <<'EOF'
import { $internal } from '../common';
import type { Entity } from '../entity/types';
import { getEntityId } from '../entity/utils/pack-entity';
import { getTraitInstance } from '../trait/trait-instance';
import type { Trait } from '../trait/types';
import type { World } from '../world';

/** Per-modifier relation pair tracking state. */
export type RelationTracker = {
    /** Initial pairs at factory creation / world reset: relationTraitId -> source -> targets */
    snapshot: Map<number, Map<number, Set<number>>>;
    /** Uncancelled pair additions within observation window */
    added: Map<number, Map<number, Set<number>>>;
    /** Uncancelled pair removals within observation window */
    removed: Map<number, Map<number, Set<number>>>;
    /** Pair changes within observation window */
    changed: Map<number, Map<number, Set<number>>>;
};

export function createRelationTracker(): RelationTracker {
    return {
        snapshot: new Map(),
        added: new Map(),
        removed: new Map(),
        changed: new Map(),
    };
}

/**
 * Record a pair-level event. Opposite add/remove events on the same target cancel.
 * Returns a map from tracking modifier id to whether that modifier's event was cancelled.
 */
export function markPairEvent(
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

/**
 * Update tracking queries that reference the relation trait after a pair-level event.
 */
export function updateQueriesForRelationPairChange(
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
}

/** Get a nested map by relation trait id. */
function getTargetSet(
    map: Map<number, Map<number, Set<number>>>,
    traitId: number,
    entity: Entity
): Set<number> | undefined {
    return map.get(traitId)?.get(entity);
}

/** Check if a specific pair is present in a pair event map. */
export function hasPairEvent(
    world: World,
    trackerId: number,
    relationTrait: Trait,
    entity: Entity,
    target: Entity | '*',
    type: 'add' | 'remove' | 'change'
): boolean {
    const tracker = world[$internal].relationTrackers.get(trackerId);
    if (!tracker) return false;

    const map =
        type === 'add'
            ? tracker.added
            : type === 'remove'
              ? tracker.removed
              : tracker.changed;

    const targets = getTargetSet(map, relationTrait.id, entity);
    if (!targets) return false;
    if (target === '*') return targets.size > 0;
    return targets.has(target);
}

/** Check if a specific pair existed in the initial snapshot. */
export function hasPairSnapshot(
    world: World,
    trackerId: number,
    relationTrait: Trait,
    entity: Entity,
    target: Entity | '*'
): boolean {
    const tracker = world[$internal].relationTrackers.get(trackerId);
    if (!tracker) return false;
    const targets = getTargetSet(tracker.snapshot, relationTrait.id, entity);
    if (!targets) return false;
    if (target === '*') return targets.size > 0;
    return targets.has(target);
}

/** Build the pair snapshot for a tracker from current world state. */
export function populateRelationTrackerSnapshot(world: World, tracker: RelationTracker) {
    const ctx = world[$internal];
    for (const relation of ctx.relations) {
        const relationTrait = relation[$internal].trait;
        const instance = getTraitInstance(ctx.traitInstances, relationTrait);
        if (!instance || !instance.relationTargets) continue;

        const byEntity = new Map<number, Set<number>>();
        tracker.snapshot.set(relationTrait.id, byEntity);

        const targets = instance.relationTargets;
        for (let eid = 0; eid < targets.length; eid++) {
            const relationCtx = relation[$internal];
            let entityTargets: number[] | undefined;
            if (relationCtx.exclusive) {
                const t = (targets as Array<number | undefined>)[eid];
                if (t !== undefined) entityTargets = [t];
            } else {
                entityTargets = (targets as number[][])[eid];
            }
            if (!entityTargets || entityTargets.length === 0) continue;

            // The entity index dense array holds the packed entity for each eid.
            const denseIdx = ctx.entityIndex.sparse[eid];
            const packedEntity = ctx.entityIndex.dense[denseIdx];
            if (packedEntity === undefined || getEntityId(packedEntity) !== eid) continue;

            byEntity.set(packedEntity, new Set(entityTargets));
        }
    }
}
EOF
# Also clean check-query-tracking.ts debug logs
python3 - <<'PY'
p='packages/core/src/query/utils/check-query-tracking.ts'
s=open(p).read()
s=s.replace("""        if (affected && group.pairs && group.pairs.length > 0) {
            console.log('CQ', 'ev', eventType, 'gt', groupType, 'gl', groupLogic, 'gid', group.id, 'canceled', pairCanceledByTracker?.get(group.id), 'target', target);
        }
""", "")
open(p,'w').write(s)
PY
echo "rewritten and cleaned"
grep -n "console.log\|canceled = false\|canceledByTracker" packages/core/src/relation/tracking.ts packages/core/src/query/utils/check-query-tracking.ts