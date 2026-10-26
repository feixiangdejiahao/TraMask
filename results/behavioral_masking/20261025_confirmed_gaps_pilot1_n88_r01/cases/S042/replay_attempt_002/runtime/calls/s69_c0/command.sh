cd /app && python3 - <<'PY'
p='packages/core/src/query/query.ts'
s=open(p).read()
# Insert helper before export function createQueryInstance
marker = "export function createQueryInstance"
helper = '''/**
 * Evaluate a tracking query against accumulated state at query creation time.
 * Unlike checkQueryTracking (which uses incremental per-query trackers), this
 * reads the persistent tracking masks and pair event state directly.
 */
function checkQueryTrackingAtCreation(world: World, query: QueryInstance, entity: Entity): boolean {
    // Static constraints first.
    if (!checkQuery(world, query, entity)) return false;

    const ctx = world[$internal];
    const eid = getEntityId(entity);
    let hasOrGroup = false;
    let anyOrMatched = false;

    for (const group of query.trackingGroups) {
        const { type, id, logic } = group;

        // Pair groups are satisfied from pair-level event state.
        if (group.pairs && group.pairs.length > 0) {
            const pair = group.pairs[0];
            const pairCtx = pair[$internal];
            const trait = pairCtx.relation[$internal].trait;
            const target = pairCtx.target;

            let traitMatches = false;
            switch (type) {
                case 'add':
                    traitMatches =
                        hasPairEvent(world, id, trait, entity, target, 'add') &&
                        hasRelationPair(world, entity, pair);
                    break;
                case 'remove':
                    traitMatches = hasPairEvent(world, id, trait, entity, target, 'remove');
                    break;
                case 'change':
                    traitMatches =
                        hasPairEvent(world, id, trait, entity, target, 'change') &&
                        hasRelationPair(world, entity, pair);
                    break;
            }

            if (logic === 'or') {
                hasOrGroup = true;
                if (traitMatches) anyOrMatched = true;
            } else if (!traitMatches) {
                return false;
            }
            continue;
        }

        // Trait-level group.
        const bitmasks = group.bitmasks;
        const snapshot = ctx.trackingSnapshots.get(id)!;
        const dirtyMask = ctx.dirtyMasks.get(id)!;
        const changedMask = ctx.changedMasks.get(id)!;

        let groupMatches = logic === 'and'; // AND starts true, OR starts false

        for (let genId = 0; genId < bitmasks.length; genId++) {
            const mask = bitmasks[genId];
            if (!mask) continue;

            const oldMask = snapshot[genId]?.[eid] || 0;
            const currentMask = ctx.entityMasks[genId]?.[eid] || 0;

            for (let bit = 1; bit <= mask; bit <<= 1) {
                if (!(mask & bit)) continue;

                let traitMatches = false;
                switch (type) {
                    case 'add':
                        traitMatches = (oldMask & bit) === 0 && (currentMask & bit) === bit;
                        break;
                    case 'remove':
                        traitMatches =
                            ((oldMask & bit) === bit && (currentMask & bit) === 0) ||
                            ((oldMask & bit) === 0 &&
                                (currentMask & bit) === 0 &&
                                ((dirtyMask[genId]?.[eid] ?? 0) & bit) === bit);
                        break;
                    case 'change':
                        traitMatches = ((changedMask[genId]?.[eid] ?? 0) & bit) === bit;
                        break;
                }

                if (logic === 'and') {
                    if (!traitMatches) {
                        groupMatches = false;
                        break;
                    }
                } else {
                    if (traitMatches) {
                        groupMatches = true;
                        break;
                    }
                }
            }

            if (logic === 'and' && !groupMatches) break;
            if (logic === 'or' && groupMatches) break;
        }

        if (logic === 'or') {
            hasOrGroup = true;
            if (groupMatches) anyOrMatched = true;
        } else if (!groupMatches) {
            return false;
        }
    }

    if (hasOrGroup && !anyOrMatched) return false;
    return true;
}

'''
assert marker in s
s=s.replace(marker, helper + marker)
# Replace initial populate block
old_pop = """    // Populate query with initial matching entities
    if (query.trackingGroups.length > 0) {
        // For tracking queries, check each entity against tracking groups
        for (const group of query.trackingGroups) {
            const { type, id, logic, bitmasks } = group;
            const snapshot = ctx.trackingSnapshots.get(id)!;
            const dirtyMask = ctx.dirtyMasks.get(id)!;
            const changedMask = ctx.changedMasks.get(id)!;

            for (const entity of ctx.entityIndex.dense) {
                // For AND groups, skip if already in query (will be checked by other groups)
                // For OR groups, skip if already in query
                if (query.entities.has(entity)) continue;

                const eid = getEntityId(entity);
                let matches = logic === 'and'; // AND starts true, OR starts false

                // Check each generation that has bitmasks
                for (let genId = 0; genId < bitmasks.length; genId++) {
                    const mask = bitmasks[genId];
                    if (!mask) continue;

                    const oldMask = snapshot[genId]?.[eid] || 0;
                    const currentMask = ctx.entityMasks[genId]?.[eid] || 0;

                    // Check each bit in the mask
                    for (let bit = 1; bit <= mask; bit <<= 1) {
                        if (!(mask & bit)) continue;

                        let traitMatches = false;

                        switch (type) {
                            case 'add':
                                traitMatches = (oldMask & bit) === 0 && (currentMask & bit) === bit;
                                break;
                            case 'remove':
                                traitMatches =
                                    ((oldMask & bit) === bit && (currentMask & bit) === 0) ||
                                    ((oldMask & bit) === 0 &&
                                        (currentMask & bit) === 0 &&
                                        ((dirtyMask[genId]?.[eid] ?? 0) & bit) === bit);
                                break;
                            case 'change':
                                traitMatches = ((changedMask[genId]?.[eid] ?? 0) & bit) === bit;
                                break;
                        }

                        if (logic === 'and') {
                            if (!traitMatches) {
                                matches = false;
                                break;
                            }
                        } else {
                            // OR logic
                            if (traitMatches) {
                                matches = true;
                                break;
                            }
                        }
                    }

                    // Early exit for AND that failed or OR that succeeded
                    if (logic === 'and' && !matches) break;
                    if (logic === 'or' && matches) break;
                }

                if (matches) {
                    if (hasRelationFilters) {
                        let relationMatch = true;
                        for (const pair of query.relationFilters!) {
                            if (!hasRelationPair(world, entity, pair)) {
                                relationMatch = false;
                                break;
                            }
                        }
                        if (relationMatch) query.add(entity);
                    } else {
                        query.add(entity);
                    }
                }
            }
        }
    } else {"""
new_pop = """    // Populate query with initial matching entities
    if (query.trackingGroups.length > 0) {
        // For tracking queries, evaluate all tracking groups together so that
        // AND groups are only satisfied when every group matches.
        for (const entity of ctx.entityIndex.dense) {
            if (!checkQueryTrackingAtCreation(world, query, entity)) continue;

            if (hasRelationFilters) {
                let relationMatch = true;
                for (const pair of query.relationFilters!) {
                    if (!hasRelationPair(world, entity, pair)) {
                        relationMatch = false;
                        break;
                    }
                }
                if (relationMatch) query.add(entity);
            } else {
                query.add(entity);
            }
        }
    } else {"""
assert old_pop in s
s=s.replace(old_pop, new_pop)
open(p,'w').write(s)
print('populate replaced')
PY