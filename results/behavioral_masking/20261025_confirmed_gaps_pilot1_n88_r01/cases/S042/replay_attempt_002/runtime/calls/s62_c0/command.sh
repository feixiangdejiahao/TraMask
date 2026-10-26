cd /app && cat > packages/core/src/query/utils/check-query-tracking.ts <<'EOF'
import { $internal } from '../../common';
import type { Entity } from '../../entity/types';
import { getEntityId } from '../../entity/utils/pack-entity';
import { hasRelationPair } from '../../relation/relation';
import { getTraitInstance } from '../../trait/trait-instance';
import type { Trait } from '../../trait/types';
import type { World } from '../../world';
import type { EventType, QueryInstance } from '../types';

/**
 * Check if an entity matches a tracking query with event handling.
 *
 * PERF: This is a hot path - optimizations applied:
 * - Cache all property accesses at function start
 * - Use `| 0` instead of `|| 0` (bitwise coerces undefined to 0)
 * - Avoid optional chaining in inner loops
 * - Cache array references before mutation
 * - Early exits where possible
 */
export function checkQueryTracking(
    world: World,
    query: QueryInstance,
    entity: Entity,
    eventType: EventType,
    eventGenerationId: number,
    eventBitflag: number,
    target?: Entity
): boolean {
    // Cache all property accesses upfront
    const staticBitmasks = query.staticBitmasks;
    const trackingGroups = query.trackingGroups;
    const generations = query.generations;
    const traitInstancesAll = query.traitInstances.all;
    const entityMasks = world[$internal].entityMasks;
    const eid = getEntityId(entity);

    const generationsLen = generations.length;
    const trackingGroupsLen = trackingGroups.length;

    // Early exit: no traits to check
    if (traitInstancesAll.length === 0) return false;

    // 1. Check static constraints (required/forbidden/or)
    for (let i = 0; i < generationsLen; i++) {
        const generationId = generations[i];
        const bitmask = staticBitmasks[i];
        if (!bitmask) continue;

        const required = bitmask.required;
        const forbidden = bitmask.forbidden;
        const or = bitmask.or;

        // PERF: Direct access + bitwise OR coerces undefined to 0
        const genMasks = entityMasks[generationId];
        const entityMask = genMasks ? (genMasks[eid] | 0) : 0;

        // Check forbidden traits
        if (forbidden && (entityMask & forbidden) !== 0) return false;

        // Check required traits
        if (required && (entityMask & required) !== required) return false;

        // Check Or traits
        if (or !== 0 && (entityMask & or) === 0) return false;
    }

    // 2. Process tracking groups - update trackers and check cross-event invalidation
    // Also track OR group state to avoid second loop when possible
    let hasOrGroup = false;
    let anyOrMatched = false;

    for (let i = 0; i < trackingGroupsLen; i++) {
        const group = trackingGroups[i];
        const groupType = group.type;
        const groupLogic = group.logic;
        const groupBitmasks = group.bitmasks;
        const groupBitmask = groupBitmasks[eventGenerationId];

        // Determine whether this event affects this group. Pair groups are only
        // affected when the incoming target matches their tracked pair.
        let affected = !!(groupBitmask && (groupBitmask & eventBitflag));
        if (affected && group.pairs && group.pairs.length > 0) {
            const pair = group.pairs[0];
            const pairCtx = pair[$internal];
            const pairRelationTrait = pairCtx.relation[$internal].trait;
            const pairInstance = getTraitInstance(world[$internal].traitInstances, pairRelationTrait);
            const pairGeneration = pairInstance?.generationId;
            const pairBitflag = pairInstance?.bitflag;

            const eventIsPairTrait =
                pairGeneration === eventGenerationId && pairBitflag === eventBitflag;

            if (!eventIsPairTrait) {
                // Regular trait event: pair group unaffected.
                affected = false;
            } else {
                const pairTarget = pairCtx.target;
                if (pairTarget !== '*' && target !== pairTarget) {
                    affected = false;
                }
            }
        }

        if (affected) {
            // Cross-event invalidation:
            // - Remove event invalidates Added/Changed tracking
            // - Add event invalidates Removed/Changed tracking
            if (eventType === 'remove') {
                if (groupType === 'add' || groupType === 'change') return false;
            } else if (eventType === 'add') {
                if (groupType === 'remove' || groupType === 'change') return false;
            }

            // Update tracker if event type matches group type
            if (groupType === eventType) {
                // For change events, verify entity still has the trait / pair
                if (eventType === 'change') {
                    if (group.pairs && group.pairs.length > 0) {
                        if (!hasRelationPair(world, entity, group.pairs[0])) return false;
                    } else {
                        const genMasks = entityMasks[eventGenerationId];
                        const entityMask = genMasks ? (genMasks[eid] | 0) : 0;
                        if (!(entityMask & eventBitflag)) return false;
                    }
                }

                // PERF: Cache tracker array reference before mutation
                const groupTrackers = group.trackers;
                let trackerArr = groupTrackers[eventGenerationId];
                if (!trackerArr) {
                    trackerArr = [];
                    groupTrackers[eventGenerationId] = trackerArr;
                }
                trackerArr[eid] = (trackerArr[eid] | 0) | eventBitflag;
            }
        }

        // 3. Verify tracking group satisfaction (merged into same loop)
        if (groupLogic === 'or') {
            hasOrGroup = true;
            if (!anyOrMatched) {
                // Check if any trait in OR group has been tracked
                const groupTrackers = group.trackers;
                const bitmaskLen = groupBitmasks.length;
                for (let genId = 0; genId < bitmaskLen; genId++) {
                    const mask = groupBitmasks[genId];
                    if (!mask) continue;
                    const trackerArr = groupTrackers[genId];
                    const tracker = trackerArr ? (trackerArr[eid] | 0) : 0;
                    if (tracker & mask) {
                        anyOrMatched = true;
                        break;
                    }
                }
            }
        } else {
            // AND group: all traits must be tracked
            const groupTrackers = group.trackers;
            const bitmaskLen = groupBitmasks.length;
            for (let genId = 0; genId < bitmaskLen; genId++) {
                const mask = groupBitmasks[genId];
                if (!mask) continue;
                const trackerArr = groupTrackers[genId];
                const tracker = trackerArr ? (trackerArr[eid] | 0) : 0;
                if ((tracker & mask) !== mask) {
                    return false;
                }
            }
        }
    }

    // If we have OR groups, at least one must match
    if (hasOrGroup && !anyOrMatched) {
        return false;
    }

    return true;
}
EOF
echo done