cd /app && cat > packages/core/src/query/query-result.ts <<'EOF'
import { $internal } from '../common';
import type { Entity } from '../entity/types';
import { getEntityId } from '../entity/utils/pack-entity';
import { getRelationData, setRelationData } from '../relation/relation';
import type { Relation, RelationPair } from '../relation/types';
import { isRelationPair } from '../relation/utils/is-relation';
import { Store } from '../storage';
import { getStore } from '../trait/trait';
import type { Trait } from '../trait/types';
import { shallowEqual } from '../utils/shallow-equal';
import type { World } from '../world';
import { isModifier } from './modifier';
import { setChanged, setPairChanged } from './modifiers/changed';
import type {
    InstancesFromParameters,
    QueryInstance,
    QueryParameter,
    QueryResult,
    QueryResultOptions,
    StoresFromParameters,
} from './types';

export function createQueryResult<T extends QueryParameter[]>(
    world: World,
    entities: Entity[],
    query: QueryInstance,
    params: QueryParameter[]
): QueryResult<T> {
    const traits: Trait[] = [];
    const stores: Store<any>[] = [];
    const relationPairs: (RelationPair | undefined)[] = [];

    getQueryStores(params, traits, stores, relationPairs, world);

    const results = Object.assign(entities, {
        readEach(
            callback: (state: InstancesFromParameters<T>, entity: Entity, index: number) => void
        ) {
            const state = Array.from({ length: traits.length }) as InstancesFromParameters<T>;

            for (let i = 0; i < entities.length; i++) {
                const entity = entities[i];

                // Create snapshots without atomic tracking
                createSnapshots(world, entity, traits, stores, relationPairs, state);

                callback(state, entity, i);
            }

            return results;
        },

        updateEach(
            callback: (state: InstancesFromParameters<T>, entity: Entity, index: number) => void,
            options: QueryResultOptions = { changeDetection: 'auto' }
        ) {
            const state = Array.from({ length: traits.length });

            // Inline all three permutations of updateEach for performance.
            if (options.changeDetection === 'auto') {
                const changedPairs: [Entity, Trait, Entity?][] = [];
                const atomicSnapshots: any[] = [];
                const trackedIndices: number[] = [];
                const untrackedIndices: number[] = [];

                getTrackedTraits(traits, world, query, trackedIndices, untrackedIndices);

                for (let i = 0; i < entities.length; i++) {
                    const entity = entities[i];
                    const eid = getEntityId(entity);

                    createSnapshotsWithAtomic(world, entity, traits, stores, relationPairs, state, atomicSnapshots);
                    callback(state as unknown as InstancesFromParameters<T>, entity, i);

                    // Skip if the entity has been destroyed.
                    if (!world.has(entity)) continue;

                    // Commit all changes back to the stores for tracked traits.
                    for (let j = 0; j < trackedIndices.length; j++) {
                        const index = trackedIndices[j];
                        const trait = traits[index];
                        const newValue = state[index];
                        const oldValue = atomicSnapshots[index];

                        const changed = commitPairOrTrait(
                            world,
                            entity,
                            eid,
                            trait,
                            stores[index],
                            relationPairs[index],
                            newValue,
                            oldValue
                        );

                        // Collect changed traits.
                        if (changed) {
                            const pair = relationPairs[index];
                            changedPairs.push([
                                entity,
                                trait,
                                pair && typeof pair[$internal].target === 'number'
                                    ? pair[$internal].target
                                    : undefined,
                            ]);
                        }
                    }

                    // Commit all changes back to the stores for untracked traits.
                    for (let j = 0; j < untrackedIndices.length; j++) {
                        const index = untrackedIndices[j];
                        const trait = traits[index];
                        const newValue = state[index];

                        commitPairOrTrait(
                            world,
                            entity,
                            eid,
                            trait,
                            stores[index],
                            relationPairs[index],
                            newValue,
                            undefined
                        );
                    }
                }

                // Trigger change events for each entity that was modified.
                for (let i = 0; i < changedPairs.length; i++) {
                    const [entity, trait, target] = changedPairs[i];
                    if (target !== undefined) {
                        setPairChanged(world, entity, trait, target);
                    } else {
                        setChanged(world, entity, trait);
                    }
                }
            } else if (options.changeDetection === 'always') {
                const changedPairs: [Entity, Trait, Entity?][] = [];
                const atomicSnapshots: any[] = [];

                for (let i = 0; i < entities.length; i++) {
                    const entity = entities[i];
                    const eid = getEntityId(entity);

                    createSnapshotsWithAtomic(world, entity, traits, stores, relationPairs, state, atomicSnapshots);
                    callback(state as unknown as InstancesFromParameters<T>, entity, i);

                    // Skip if the entity has been destroyed.
                    if (!world.has(entity)) continue;

                    // Commit all changes back to the stores.
                    for (let j = 0; j < traits.length; j++) {
                        const trait = traits[j];
                        const newValue = state[j];

                        const changed = commitPairOrTrait(
                            world,
                            entity,
                            eid,
                            trait,
                            stores[j],
                            relationPairs[j],
                            newValue,
                            atomicSnapshots[j]
                        );

                        // Collect changed traits.
                        if (changed) {
                            const pair = relationPairs[j];
                            changedPairs.push([
                                entity,
                                trait,
                                pair && typeof pair[$internal].target === 'number'
                                    ? pair[$internal].target
                                    : undefined,
                            ]);
                        }
                    }
                }

                // Trigger change events for each entity that was modified.
                for (let i = 0; i < changedPairs.length; i++) {
                    const [entity, trait, target] = changedPairs[i];
                    if (target !== undefined) {
                        setPairChanged(world, entity, trait, target);
                    } else {
                        setChanged(world, entity, trait);
                    }
                }
            } else if (options.changeDetection === 'never') {
                for (let i = 0; i < entities.length; i++) {
                    const entity = entities[i];
                    const eid = getEntityId(entity);
                    createSnapshots(world, entity, traits, stores, relationPairs, state);
                    callback(state as unknown as InstancesFromParameters<T>, entity, i);

                    // Skip if the entity has been destroyed.
                    if (!world.has(entity)) continue;

                    // Commit all changes back to the stores.
                    for (let j = 0; j < traits.length; j++) {
                        const trait = traits[j];
                        commitPairOrTrait(
                            world,
                            entity,
                            eid,
                            trait,
                            stores[j],
                            relationPairs[j],
                            state[j],
                            undefined
                        );
                    }
                }
            }

            return results;
        },

        useStores(callback: (stores: StoresFromParameters<T>, entities: readonly Entity[]) => void) {
            callback(stores as unknown as StoresFromParameters<T>, entities);
            return results;
        },

        select<U extends QueryParameter[]>(...params: U): QueryResult<U> {
            traits.length = 0;
            stores.length = 0;
            relationPairs.length = 0;
            getQueryStores(params, traits, stores, relationPairs, world);
            return results as unknown as QueryResult<U>;
        },

        sort(
            callback: (a: Entity, b: Entity) => number = (a, b) => getEntityId(a) - getEntityId(b)
        ): QueryResult<T> {
            Array.prototype.sort.call(entities, callback);
            return results;
        },
    });

    return results;
}

/* @inline */ function getTrackedTraits(
    traits: Trait[],
    world: World,
    query: QueryInstance,
    trackedIndices: number[],
    untrackedIndices: number[]
) {
    for (let i = 0; i < traits.length; i++) {
        const trait = traits[i];
        const hasTracked = world[$internal].trackedTraits.has(trait);
        const hasChanged = query.hasChangedModifiers && query.changedTraits.has(trait);

        if (hasTracked || hasChanged) trackedIndices.push(i);
        else untrackedIndices.push(i);
    }
}

/* @inline */ function createSnapshots(
    world: World,
    entity: Entity,
    traits: Trait[],
    stores: Store<any>[],
    relationPairs: (RelationPair | undefined)[],
    state: any[]
) {
    for (let i = 0; i < traits.length; i++) {
        const trait = traits[i];
        const pair = relationPairs[i];
        const target = pair && typeof pair[$internal].target === 'number' ? pair[$internal].target : undefined;

        if (target !== undefined) {
            const relation = pair![$internal].relation as Relation<Trait>;
            state[i] = getRelationData(world, entity, relation, target);
        } else {
            const ctx = trait[$internal];
            state[i] = ctx.get(getEntityId(entity), stores[i]);
        }
    }
}

/* @inline */ function createSnapshotsWithAtomic(
    world: World,
    entity: Entity,
    traits: Trait[],
    stores: Store<any>[],
    relationPairs: (RelationPair | undefined)[],
    state: any[],
    atomicSnapshots: any[]
) {
    for (let j = 0; j < traits.length; j++) {
        const trait = traits[j];
        const pair = relationPairs[j];
        const target = pair && typeof pair[$internal].target === 'number' ? pair[$internal].target : undefined;

        if (target !== undefined) {
            const relation = pair![$internal].relation as Relation<Trait>;
            const value = getRelationData(world, entity, relation, target);
            state[j] = value;
            atomicSnapshots[j] = trait[$internal].type === 'aos' ? { ...value } : null;
        } else {
            const ctx = trait[$internal];
            const value = ctx.get(getEntityId(entity), stores[j]);
            state[j] = value;
            atomicSnapshots[j] = ctx.type === 'aos' ? { ...value } : null;
        }
    }
}

/* @inline */ function commitPairOrTrait(
    world: World,
    entity: Entity,
    eid: number,
    trait: Trait,
    store: Store<any>,
    pair: RelationPair | undefined,
    newValue: any,
    oldValue: any
): boolean {
    const target = pair && typeof pair[$internal].target === 'number' ? pair[$internal].target : undefined;

    if (target !== undefined) {
        const relation = pair![$internal].relation as Relation<Trait>;
        const previous = getRelationData(world, entity, relation, target);
        const changed = !shallowEqual(previous, newValue);
        if (changed) setRelationData(world, entity, relation, target, newValue);
        return changed;
    }

    const ctx = trait[$internal];
    if (ctx.type === 'aos') {
        const changed = ctx.fastSetWithChangeDetection(eid, store, newValue);
        if (!changed) {
            return !shallowEqual(newValue, oldValue);
        }
        return changed;
    }
    return ctx.fastSetWithChangeDetection(eid, store, newValue);
}

/* @inline */ export function getQueryStores<T extends QueryParameter[]>(
    params: T,
    traits: Trait[],
    stores: Store<any>[],
    relationPairs: (RelationPair | undefined)[],
    world: World
) {
    for (let i = 0; i < params.length; i++) {
        const param = params[i];

        // Handle relation pairs
        if (isRelationPair(param)) {
            const pairCtx = param[$internal];
            const relation = pairCtx.relation as Relation<Trait>;
            const baseTrait = relation[$internal].trait;
            if (baseTrait[$internal].type !== 'tag') {
                traits.push(baseTrait);
                stores.push(getStore(world, baseTrait));
                relationPairs.push(typeof pairCtx.target === 'number' ? param : undefined);
            }
            continue;
        }

        if (isModifier(param)) {
            // Skip not modifier.
            if (param.type === 'not') continue;

            const pairTraits = new Set<number>();
            if (param.pairs) {
                for (const pair of param.pairs) {
                    const pairCtx = pair[$internal];
                    const relation = pairCtx.relation as Relation<Trait>;
                    const baseTrait = relation[$internal].trait;
                    pairTraits.add(baseTrait.id);
                    if (baseTrait[$internal].type === 'tag') continue;

                    traits.push(baseTrait);
                    stores.push(getStore(world, baseTrait));
                    relationPairs.push(typeof pairCtx.target === 'number' ? pair : undefined);
                }
            }

            const modifierTraits = param.traits;
            for (const trait of modifierTraits) {
                if (pairTraits.has(trait.id)) continue; // Already included via pair
                if (trait[$internal].type === 'tag') continue; // Skip tags
                traits.push(trait);
                stores.push(getStore(world, trait));
                relationPairs.push(undefined);
            }
        } else {
            const trait = param as Trait;
            if (trait[$internal].type === 'tag') continue; // Skip tags
            traits.push(trait);
            stores.push(getStore(world, trait));
            relationPairs.push(undefined);
        }
    }
}

export function createEmptyQueryResult(): QueryResult<QueryParameter[]> {
    const results = Object.assign([], {
        readEach: () => results,
        updateEach: () => results,
        useStores: () => results,
        select: () => results,
        sort: () => results,
    }) as QueryResult<QueryParameter[]>;

    return results;
}

// Cached no-op result methods for relation-only queries
const relationOnlyMethods = {
    readEach(this: QueryResult<any>, callback: any) {
        // No traits to read, just iterate entities
        for (let i = 0; i < this.length; i++) {
            callback([], this[i], i);
        }
        return this;
    },
    updateEach(this: QueryResult<any>, callback: any) {
        // No traits to update, just iterate entities
        for (let i = 0; i < this.length; i++) {
            callback([], this[i], i);
        }
        return this;
    },
    useStores(this: QueryResult<any>, callback: any) {
        // No stores, call with empty array
        callback([], this);
        return this;
    },
    select(this: QueryResult<any>) {
        // No-op, nothing to select
        return this;
    },
};

/**
 * Lightweight query result for relation-only queries.
 * Skips store/trait setup since we only need to iterate entities.
 */
export function createRelationOnlyQueryResult<T extends QueryParameter[]>(
    entities: Entity[]
): QueryResult<T> {
    const results = Object.assign(entities, {
        readEach: relationOnlyMethods.readEach,
        updateEach: relationOnlyMethods.updateEach,
        useStores: relationOnlyMethods.useStores,
        select: relationOnlyMethods.select,
        sort(
            callback: (a: Entity, b: Entity) => number = (a, b) => getEntityId(a) - getEntityId(b)
        ): QueryResult<T> {
            Array.prototype.sort.call(entities, callback);
            return results;
        },
    }) as unknown as QueryResult<T>;

    return results;
}
EOF
echo done