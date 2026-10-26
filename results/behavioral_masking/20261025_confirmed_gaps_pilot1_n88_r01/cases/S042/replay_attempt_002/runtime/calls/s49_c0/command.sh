cd /app && cat > packages/core/src/query/modifier.ts <<'EOF'
import { Brand } from '../common';
import type { RelationPair } from '../relation/types';
import { isRelation, isRelationPair } from '../relation/utils/is-relation';
import type { Trait } from '../trait/types';
import { EventType, Modifier, OrModifier, QueryParameter } from './types';

export const $modifier = Symbol('modifier');

export function createModifier<TTrait extends Trait[] = Trait[], TType extends string = string>(
    type: TType,
    id: number,
    traits: TTrait,
    pairs: RelationPair[] = []
): Modifier<TTrait, TType> {
    return {
        [$modifier]: true,
        type,
        id,
        traits,
        traitIds: traits.map((trait) => trait.id),
        pairs,
    } as const;
}

export /* @inline @pure */ function isModifier(param: QueryParameter): param is Modifier {
    return (param as Brand<typeof $modifier> | null | undefined)?.[$modifier] as unknown as boolean;
}

/** Check if a modifier is a tracking modifier (added, removed, or changed) */
export function isTrackingModifier(modifier: Modifier): boolean {
    const { type } = modifier;
    return type.includes('added') || type.includes('removed') || type.includes('changed');
}

/** Get the tracking type from a modifier */
export function getTrackingType(modifier: Modifier): EventType | null {
    const { type } = modifier;
    if (type.includes('added')) return 'add';
    if (type.includes('removed')) return 'remove';
    if (type.includes('changed')) return 'change';
    return null;
}

/** Check if an Or modifier has nested modifiers */
export function isOrWithModifiers(modifier: Modifier): modifier is OrModifier {
    return modifier.type === 'or' && Array.isArray((modifier as OrModifier).modifiers);
}
EOF
cat > packages/core/src/query/modifiers/added.ts <<'EOF'
import { isRelation, isRelationPair } from '../../relation/utils/is-relation';
import type { RelationPair } from '../../relation/types';
import type { ExtractTraits, TraitOrRelation } from '../../trait/types';
import { universe } from '../../universe/universe';
import { createModifier } from '../modifier';
import type { Modifier } from '../types';
import { createTrackingId, setTrackingMasks } from '../utils/tracking-cursor';

export function createAdded() {
    const id = createTrackingId();

    for (const world of universe.worlds) {
        if (!world) continue;
        setTrackingMasks(world, id);
    }

    return <T extends TraitOrRelation[]>(
        ...inputs: T
    ): Modifier<ExtractTraits<T>, `added-${number}`> => {
        const pairs: RelationPair[] = [];
        const traits = inputs.map((input) => {
            if (isRelation(input)) return input[$internal].trait;
            if (isRelationPair(input)) {
                pairs.push(input);
                return input[$internal].relation[$internal].trait;
            }
            return input;
        }) as ExtractTraits<T>;
        return createModifier(`added-${id}`, id, traits, pairs);
    };
}
EOF
cat > packages/core/src/query/modifiers/removed.ts <<'EOF'
import { isRelation, isRelationPair } from '../../relation/utils/is-relation';
import type { RelationPair } from '../../relation/types';
import type { ExtractTraits, TraitOrRelation } from '../../trait/types';
import { universe } from '../../universe/universe';
import { createModifier } from '../modifier';
import type { Modifier } from '../types';
import { createTrackingId, setTrackingMasks } from '../utils/tracking-cursor';

export function createRemoved() {
    const id = createTrackingId();

    for (const world of universe.worlds) {
        if (!world) continue;
        setTrackingMasks(world, id);
    }

    return <T extends TraitOrRelation[]>(
        ...inputs: T
    ): Modifier<ExtractTraits<T>, `removed-${number}`> => {
        const pairs: RelationPair[] = [];
        const traits = inputs.map((input) => {
            if (isRelation(input)) return input[$internal].trait;
            if (isRelationPair(input)) {
                pairs.push(input);
                return input[$internal].relation[$internal].trait;
            }
            return input;
        }) as ExtractTraits<T>;
        return createModifier(`removed-${id}`, id, traits, pairs);
    };
}
EOF
cat > packages/core/src/query/modifiers/changed.ts <<'EOF'
import { $internal } from '../../common';
import type { Entity } from '../../entity/types';
import { getEntityId } from '../../entity/utils/pack-entity';
import { hasRelationPair } from '../../relation/relation';
import { isRelation, isRelationPair } from '../../relation/utils/is-relation';
import type { RelationPair } from '../../relation/types';
import { hasTrait, registerTrait } from '../../trait/trait';
import { getTraitInstance, hasTraitInstance } from '../../trait/trait-instance';
import type { ExtractTraits, Trait, TraitOrRelation } from '../../trait/types';
import { universe } from '../../universe/universe';
import type { World } from '../../world';
import { createModifier } from '../modifier';
import type { Modifier } from '../types';
import { checkQueryTrackingWithRelations } from '../utils/check-query-tracking-with-relations';
import { createTrackingId, setTrackingMasks } from '../utils/tracking-cursor';

export function createChanged() {
    const id = createTrackingId();

    for (const world of universe.worlds) {
        if (!world) continue;
        setTrackingMasks(world, id);
    }

    return <T extends TraitOrRelation[]>(
        ...inputs: T
    ): Modifier<ExtractTraits<T>, `changed-${number}`> => {
        const pairs: RelationPair[] = [];
        const traits = inputs.map((input) => {
            if (isRelation(input)) return input[$internal].trait;
            if (isRelationPair(input)) {
                pairs.push(input);
                return input[$internal].relation[$internal].trait;
            }
            return input;
        }) as ExtractTraits<T>;
        return createModifier(`changed-${id}`, id, traits, pairs);
    };
}

/** @inline */
function markChanged(world: World, entity: Entity, trait: Trait) {
    const ctx = world[$internal];

    // Early exit if the trait is not on the entity.
    if (!hasTrait(world, entity, trait)) return;

    // Register the trait if it's not already registered.
    if (!hasTraitInstance(ctx.traitInstances, trait)) registerTrait(world, trait);
    const data = getTraitInstance(ctx.traitInstances, trait)!;

    // Mark the trait as changed in bitmasks for Changed modifiers.
    const eid = getEntityId(entity);
    const { generationId, bitflag } = data;

    for (const changedMask of ctx.changedMasks.values()) {
        if (!changedMask[generationId]) changedMask[generationId] = [];
        if (!changedMask[generationId][eid]) changedMask[generationId][eid] = 0;
        changedMask[generationId][eid] |= bitflag;
    }

    // Update tracking queries with change event
    for (const query of data.trackingQueries) {
        if (!query.hasChangedModifiers) continue;
        if (!query.changedTraits.has(trait)) continue;

        const match =
            query.relationFilters && query.relationFilters.length > 0
                ? checkQueryTrackingWithRelations(
                      world,
                      query,
                      entity,
                      'change',
                      generationId,
                      bitflag
                  )
                : query.checkTracking(world, entity, 'change', generationId, bitflag);
        if (match) query.add(entity);
        else query.remove(world, entity);
    }

    return data;
}

export function setChanged(world: World, entity: Entity, trait: Trait) {
    const data = markChanged(world, entity, trait);
    if (!data) return;
    for (const sub of data.changeSubscriptions) sub(entity);
}

export function setPairChanged(world: World, entity: Entity, trait: Trait, target: Entity) {
    const data = markChanged(world, entity, trait);
    if (!data) return;

    // Mark pair-level change and update pair tracking queries.
    markPairEvent(world, trait, entity, target, 'change');
    updateQueriesForRelationPairChange(world, trait, entity, target, 'change');

    for (const sub of data.changeSubscriptions) sub(entity, target);
}

export function markPairEvent(
    world: World,
    relationTrait: Trait,
    entity: Entity,
    target: Entity,
    type: 'add' | 'remove' | 'change'
) {
    const ctx = world[$internal];
    const traitId = relationTrait.id;

    for (const tracker of ctx.relationTrackers.values()) {
        const eventMap = type === 'add' ? tracker.added : type === 'remove' ? tracker.removed : tracker.changed;
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

        if (type === 'add') {
            const removedByEntity = tracker.removed.get(traitId);
            const removedTargets = removedByEntity?.get(entity);
            if (removedTargets?.delete(target)) {
                // Cancel the opposite removal
                if (removedTargets.size === 0) removedByEntity!.delete(entity);
            } else {
                targets.add(target);
            }
        } else if (type === 'remove') {
            const addedByEntity = tracker.added.get(traitId);
            const addedTargets = addedByEntity?.get(entity);
            if (addedTargets?.delete(target)) {
                // Cancel the opposite addition
                if (addedTargets.size === 0) addedByEntity!.delete(entity);
            } else {
                targets.add(target);
            }
        } else {
            targets.add(target);
        }
    }
}

export function updateQueriesForRelationPairChange(
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
}
EOF
echo done