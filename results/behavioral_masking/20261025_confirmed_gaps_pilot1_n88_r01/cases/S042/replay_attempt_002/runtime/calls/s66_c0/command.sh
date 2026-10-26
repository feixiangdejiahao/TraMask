cd /app && python3 - <<'PY'
p='packages/core/src/query/query.ts'
s=open(p).read()
old = """/**
 * Unified function to process tracking modifiers with explicit AND/OR logic.
 * Groups modifiers by (type, id, logic) key so same-tracker calls are combined.
 */
function processTrackingModifier(
    world: World,
    query: QueryInstance,
    modifier: Modifier,
    logic: 'and' | 'or',
    ctx: World[typeof $internal],
    groupsMap: Map<string, TrackingGroup>
): void {
    const trackingType = getTrackingType(modifier);
    if (!trackingType) return;

    const id = modifier.id;
    // Key includes logic so Changed(A) at top-level stays separate from Or(Changed(A))
    const key = `${trackingType}-${id}-${logic}`;

    // Find or create tracking group
    let group = groupsMap.get(key);
    if (!group) {
        group = {
            logic,
            type: trackingType,
            id,
            bitmasks: [],
            trackers: [],
        };
        groupsMap.set(key, group);
        query.trackingGroups.push(group);
    }

    // Register traits and build bitmasks
    for (const trait of modifier.traits) {
        if (!hasTraitInstance(ctx.traitInstances, trait)) registerTrait(world, trait);
        const instance = getTraitInstance(ctx.traitInstances, trait)!;
        query.traits.push(trait);

        // Add to traitInstances.all for query registration
        query.traitInstances.all.push(instance);

        // Build bitmasks by generation
        const genId = instance.generationId;
        group.bitmasks[genId] = (group.bitmasks[genId] || 0) | instance.bitflag;

        // Track changed traits for change detection in query-result
        if (trackingType === 'change') {
            query.changedTraits.add(trait);
            query.hasChangedModifiers = true;
        }
    }

    query.isTracking = true;
}
"""
new = """/**
 * Unified function to process tracking modifiers with explicit AND/OR logic.
 * Pair inputs are split into their own tracking groups so each target is tracked
 * independently while still composing with traits and other modifiers.
 */
function processTrackingModifier(
    world: World,
    query: QueryInstance,
    modifier: Modifier,
    logic: 'and' | 'or',
    ctx: World[typeof $internal],
    groupsMap: Map<string, TrackingGroup>
): void {
    const trackingType = getTrackingType(modifier);
    if (!trackingType) return;

    const id = modifier.id;
    const pairs = modifier.pairs ?? [];
    const pairTraitIds = new Set<number>();

    // Each relation pair becomes its own tracking group so per-target state is distinct.
    for (const pair of pairs) {
        const pairCtx = pair[$internal];
        const relation = pairCtx.relation as Relation<Trait>;
        const trait = relation[$internal].trait;
        pairTraitIds.add(trait.id);

        const target = pairCtx.target;
        const key = `${trackingType}-${id}-${logic}-pair:${trait.id}:${target}`;

        let group = groupsMap.get(key);
        if (!group) {
            group = {
                logic,
                type: trackingType,
                id,
                bitmasks: [],
                trackers: [],
                pairs: [pair],
            };
            groupsMap.set(key, group);
            query.trackingGroups.push(group);
        }

        if (!hasTraitInstance(ctx.traitInstances, trait)) registerTrait(world, trait);
        const instance = getTraitInstance(ctx.traitInstances, trait)!;
        query.traits.push(trait);
        query.traitInstances.all.push(instance);

        const genId = instance.generationId;
        group.bitmasks[genId] = (group.bitmasks[genId] || 0) | instance.bitflag;

        if (trackingType === 'change') {
            query.changedTraits.add(trait);
            query.hasChangedModifiers = true;
        }

        query.isTracking = true;
    }

    // Non-pair traits are grouped together (existing trait-level behavior).
    const regularTraits = modifier.traits.filter((trait) => !pairTraitIds.has(trait.id));
    if (regularTraits.length === 0) return;

    const key = `${trackingType}-${id}-${logic}`;

    let group = groupsMap.get(key);
    if (!group) {
        group = {
            logic,
            type: trackingType,
            id,
            bitmasks: [],
            trackers: [],
        };
        groupsMap.set(key, group);
        query.trackingGroups.push(group);
    }

    for (const trait of regularTraits) {
        if (!hasTraitInstance(ctx.traitInstances, trait)) registerTrait(world, trait);
        const instance = getTraitInstance(ctx.traitInstances, trait)!;
        query.traits.push(trait);

        // Add to traitInstances.all for query registration
        query.traitInstances.all.push(instance);

        // Build bitmasks by generation
        const genId = instance.generationId;
        group.bitmasks[genId] = (group.bitmasks[genId] || 0) | instance.bitflag;

        // Track changed traits for change detection in query-result
        if (trackingType === 'change') {
            query.changedTraits.add(trait);
            query.hasChangedModifiers = true;
        }
    }

    query.isTracking = true;
}
"""
assert old in s
s=s.replace(old,new)
open(p,'w').write(s)
print('processTrackingModifier replaced')
PY