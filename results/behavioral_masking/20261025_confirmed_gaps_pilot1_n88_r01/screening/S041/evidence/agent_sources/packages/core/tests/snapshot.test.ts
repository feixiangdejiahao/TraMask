import { beforeEach, describe, expect, it } from 'vitest';
import {
    createTraitRegistry,
    createWorld,
    diffEntitySnapshots,
    diffWorldSnapshots,
    relation,
    rollbackEntity,
    rollbackWorld,
    snapshotEntity,
    snapshotWorld,
    trait,
    type EntitySnapshot,
    type TraitRegistry,
    type WorldSnapshot,
} from '../src';

const Position = trait({ x: 0, y: 0 });
const Health = trait({ hp: 100 });
const IsPlayer = trait();
const ChildOf = relation();
const Contains = relation({ store: { amount: 0 } });
const TagRel = relation();

function makeRegistry(): TraitRegistry {
    return createTraitRegistry(
        ['position', Position],
        ['health', Health],
        ['isPlayer', IsPlayer],
        ['childOf', ChildOf],
        ['contains', Contains],
        ['tagRel', TagRel],
    );
}

describe('createTraitRegistry', () => {
    it('should create a registry from entries', () => {
        const registry = createTraitRegistry(['position', Position], ['childOf', ChildOf]);
        expect(registry.entries.position).toBe(Position);
        expect(registry.entries.childOf).toBe(ChildOf);
    });

    it('should throw on duplicate keys', () => {
        expect(() => createTraitRegistry(['a', Position], ['a', Health])).toThrow(Error);
    });

    it('should throw on duplicate traits', () => {
        expect(() => createTraitRegistry(['a', Position], ['b', Position])).toThrow(Error);
    });

    it('should throw on duplicate relations', () => {
        expect(() => createTraitRegistry(['a', ChildOf], ['b', ChildOf])).toThrow(Error);
    });
});

describe('snapshotEntity', () => {
    const world = createWorld();
    const registry = makeRegistry();

    beforeEach(() => {
        world.reset();
    });

    it('should snapshot tag traits as true and data traits as deep copies', () => {
        const entity = world.spawn(Position({ x: 1, y: 2 }), IsPlayer);
        const snapshot = snapshotEntity(world, entity, registry);

        expect(snapshot.id).toBe(entity.id());
        expect(snapshot.traits).toEqual({
            position: { x: 1, y: 2 },
            isPlayer: true,
        });
        expect(snapshot.relations).toBeUndefined();
    });

    it('should deep copy trait data', () => {
        const entity = world.spawn(Position({ x: 1, y: 2 }));
        const snapshot = snapshotEntity(world, entity, registry);
        (snapshot.traits.position as { x: number }).x = 99;
        expect(entity.get(Position)!.x).toBe(1);
    });

    it('should snapshot relations with and without data', () => {
        const player = world.spawn();
        const item = world.spawn(Contains(player, { amount: 3 }), ChildOf(player), TagRel(player));
        const snapshot = snapshotEntity(world, item, registry);

        expect(snapshot.relations).toEqual({
            contains: [{ targetId: player.id(), data: { amount: 3 } }],
            childOf: [{ targetId: player.id() }],
            tagRel: [{ targetId: player.id() }],
        });
    });

    it('should omit relations when entity has none', () => {
        const entity = world.spawn(Position());
        const snapshot = snapshotEntity(world, entity, registry);
        expect(snapshot.relations).toBeUndefined();
    });

    it('should throw for destroyed entities', () => {
        const entity = world.spawn();
        entity.destroy();
        expect(() => snapshotEntity(world, entity, registry)).toThrow(Error);
    });

    it('should throw for unregistered traits', () => {
        const Unregistered = trait();
        const entity = world.spawn(Unregistered);
        expect(() => snapshotEntity(world, entity, registry)).toThrow(Error);
    });

    it('should throw for unregistered relations', () => {
        const UnregisteredRel = relation();
        const target = world.spawn();
        const entity = world.spawn(UnregisteredRel(target));
        expect(() => snapshotEntity(world, entity, registry)).toThrow(Error);
    });
});

describe('snapshotWorld', () => {
    const world = createWorld();
    const registry = makeRegistry();

    beforeEach(() => {
        world.reset();
    });

    it('should exclude the internal world entity', () => {
        const a = world.spawn(Position());
        const b = world.spawn(Position());
        const snapshot = snapshotWorld(world, registry);
        expect(snapshot.entities.map((e) => e.id).sort()).toEqual([a.id(), b.id()].sort());
    });

    it('should return empty entities for an empty world', () => {
        const snapshot = snapshotWorld(world, registry);
        expect(snapshot.entities).toEqual([]);
    });
});

describe('rollbackEntity', () => {
    const world = createWorld();
    const registry = makeRegistry();

    beforeEach(() => {
        world.reset();
    });

    it('should restore traits and relations exactly', () => {
        const player = world.spawn();
        const item = world.spawn(Contains(player, { amount: 3 }), Position({ x: 1, y: 2 }), IsPlayer);
        const snapshot = snapshotEntity(world, item, registry);

        // Mutate state.
        item.remove(IsPlayer);
        item.set(Position, { x: 100, y: 200 });
        item.set(Contains(player), { amount: 42 });
        item.add(Health({ hp: 10 }));

        rollbackEntity(world, item, registry, snapshot);

        const after = snapshotEntity(world, item, registry);
        expect(after).toEqual(snapshot);
    });

    it('should remove traits and relations not in snapshot', () => {
        const player = world.spawn();
        const item = world.spawn(Contains(player, { amount: 1 }), Position());
        const snapshot = snapshotEntity(world, item, registry);

        item.add(Health({ hp: 50 }));
        item.add(ChildOf(player));
        item.add(TagRel(player));

        rollbackEntity(world, item, registry, snapshot);
        expect(item.has(Health)).toBe(false);
        expect(item.targetsFor(ChildOf).length).toBe(0);
        expect(item.targetsFor(TagRel).length).toBe(0);
        expect(item.has(Position)).toBe(true);
    });

    it('should throw if relation target does not exist', () => {
        const item = world.spawn(Contains(world.spawn(), { amount: 1 }));
        const snapshot = snapshotEntity(world, item, registry);

        // Destroy the target then rollback.
        const targetId = snapshot.relations!.contains[0].targetId;
        const target = world.entities.find((e) => e.id() === targetId)!;
        target.destroy();

        expect(() => rollbackEntity(world, item, registry, snapshot)).toThrow(Error);
    });

    it('should throw for destroyed entities', () => {
        const entity = world.spawn();
        const snapshot = snapshotEntity(world, entity, registry);
        entity.destroy();
        expect(() => rollbackEntity(world, entity, registry, snapshot)).toThrow(Error);
    });

    it('should throw for unknown registry keys', () => {
        const entity = world.spawn();
        const snapshot: EntitySnapshot = {
            id: entity.id(),
            traits: { notRegistered: true },
        };
        expect(() => rollbackEntity(world, entity, registry, snapshot)).toThrow(Error);
    });
});

describe('rollbackWorld', () => {
    const world = createWorld();
    const registry = makeRegistry();

    beforeEach(() => {
        world.reset();
    });

    it('should fully replace world state and recreate entity IDs', () => {
        const player = world.spawn(Position({ x: 1, y: 2 }), IsPlayer);
        const item = world.spawn(Contains(player, { amount: 3 }));
        const checkpoint = snapshotWorld(world, registry);

        // Mutate state heavily.
        world.spawn(Position({ x: 99, y: 99 }));
        player.set(Position, { x: 100, y: 200 });
        item.destroy();

        rollbackWorld(world, registry, checkpoint);

        const after = snapshotWorld(world, registry);
        expect(after).toEqual(checkpoint);

        const ids = after.entities.map((e) => e.id).sort((a, b) => a - b);
        expect(ids).toEqual([player.id(), item.id()].sort((a, b) => a - b));
        expect(world.has(player)).toBe(true);
        expect(world.has(item)).toBe(true);
    });

    it('should throw for unknown registry keys', () => {
        const badCheckpoint: WorldSnapshot = {
            entities: [{ id: 1, traits: { nope: true } }],
        };
        expect(() => rollbackWorld(world, registry, badCheckpoint)).toThrow(Error);
    });

    it('should throw for dangling relation targets', () => {
        const badCheckpoint: WorldSnapshot = {
            entities: [
                {
                    id: 1,
                    traits: {},
                    relations: { childOf: [{ targetId: 999 }] },
                },
            ],
        };
        expect(() => rollbackWorld(world, registry, badCheckpoint)).toThrow(Error);
    });

    it('should handle relations to entities that appear later in the checkpoint', () => {
        // Entity 1 relates to entity 2, but entity 2 is listed after entity 1.
        const checkpoint: WorldSnapshot = {
            entities: [
                {
                    id: 1,
                    traits: {},
                    relations: { childOf: [{ targetId: 2 }] },
                },
                { id: 2, traits: {} },
            ],
        };
        rollbackWorld(world, registry, checkpoint);
        const after = snapshotWorld(world, registry);
        expect(after.entities.length).toBe(2);
        const source = world.entities.find((e) => e.id() === 1)!;
        const target = world.entities.find((e) => e.id() === 2)!;
        expect(source.targetFor(ChildOf)).toBe(target);
    });

    it('should allow relations targeting the world entity', () => {
        const checkpoint: WorldSnapshot = {
            entities: [
                {
                    id: 1,
                    traits: {},
                    relations: { childOf: [{ targetId: 0 }] },
                },
            ],
        };
        rollbackWorld(world, registry, checkpoint);
        const source = world.entities.find((e) => e.id() === 1)!;
        const worldEntity = world.entities.find((e) => e.id() === 0)!;
        expect(source.targetFor(ChildOf)).toBe(worldEntity);
    });

    it('should support queries after rollback', () => {
        const a = world.spawn(Position({ x: 1, y: 2 }));
        const b = world.spawn(IsPlayer);
        const checkpoint = snapshotWorld(world, registry);

        world.spawn(Position({ x: 99, y: 99 }));
        rollbackWorld(world, registry, checkpoint);

        const positions = world.query(Position);
        expect(positions.length).toBe(1);
        expect(positions[0].id()).toBe(a.id());
        const players = world.query(IsPlayer);
        expect(players.length).toBe(1);
        expect(players[0].id()).toBe(b.id());
    });

    it('should recreate non-contiguous entity IDs', () => {
        const checkpoint: WorldSnapshot = {
            entities: [
                { id: 3, traits: { isPlayer: true } },
                { id: 1, traits: { isPlayer: true } },
                { id: 5, traits: {} },
            ],
        };
        rollbackWorld(world, registry, checkpoint);
        const ids = world.entities.map((e) => e.id()).sort((a, b) => a - b);
        expect(ids).toEqual([0, 1, 3, 5]);
        expect(world.entities.some((e) => e.id() === 3 && e.has(IsPlayer))).toBe(true);
        expect(world.entities.some((e) => e.id() === 1 && e.has(IsPlayer))).toBe(true);
        expect(world.entities.some((e) => e.id() === 5 && !e.has(IsPlayer))).toBe(true);
    });
});

describe('diffEntitySnapshots', () => {
    it('should compute added, removed and changed traits sorted', () => {
        const a: EntitySnapshot = {
            id: 1,
            traits: { a: true, b: { v: 1 }, c: true },
        };
        const b: EntitySnapshot = {
            id: 1,
            traits: { b: { v: 2 }, c: true, d: true },
        };
        expect(diffEntitySnapshots(a, b)).toEqual({
            addedTraits: ['d'],
            removedTraits: ['a'],
            changedTraits: ['b'],
        });
    });

    it('should use shallow equality for data', () => {
        const a: EntitySnapshot = {
            id: 1,
            traits: { a: { x: { y: 1 } } },
        };
        const b: EntitySnapshot = {
            id: 1,
            traits: { a: { x: { y: 2 } } },
        };
        // Shallow equality: nested objects differ by reference, so not equal.
        expect(diffEntitySnapshots(a, b).changedTraits).toEqual(['a']);
    });

    it('should throw for null/undefined', () => {
        expect(() => diffEntitySnapshots(null as any, {} as any)).toThrow(Error);
        expect(() => diffEntitySnapshots({} as any, undefined as any)).toThrow(Error);
    });
});

describe('diffWorldSnapshots', () => {
    it('should compute added, removed and changed ids sorted', () => {
        const before: WorldSnapshot = {
            entities: [
                { id: 1, traits: { a: true } },
                { id: 2, traits: { a: true } },
                { id: 3, traits: { a: true } },
            ],
        };
        const after: WorldSnapshot = {
            entities: [
                { id: 2, traits: { a: { value: 2 } } },
                { id: 3, traits: { a: true } },
                { id: 4, traits: { a: true } },
            ],
        };
        expect(diffWorldSnapshots(before, after)).toEqual({
            added: [4],
            removed: [1],
            changed: [2],
        });
    });

    it('should treat empty relations and missing relations as equal', () => {
        const before: WorldSnapshot = {
            entities: [{ id: 1, traits: { a: true } }],
        };
        const after: WorldSnapshot = {
            entities: [{ id: 1, traits: { a: true }, relations: {} }],
        };
        expect(diffWorldSnapshots(before, after)).toEqual({
            added: [],
            removed: [],
            changed: [],
        });
    });

    it('should ignore trait, relation and target ordering', () => {
        const before: WorldSnapshot = {
            entities: [
                {
                    id: 1,
                    traits: { a: true, b: true },
                    relations: { childOf: [{ targetId: 5 }, { targetId: 6 }] },
                },
            ],
        };
        const after: WorldSnapshot = {
            entities: [
                {
                    id: 1,
                    traits: { b: true, a: true },
                    relations: { childOf: [{ targetId: 6 }, { targetId: 5 }] },
                },
            ],
        };
        expect(diffWorldSnapshots(before, after)).toEqual({
            added: [],
            removed: [],
            changed: [],
        });
    });

    it('should throw for missing entities array or null', () => {
        expect(() => diffWorldSnapshots(null as any, {} as any)).toThrow(Error);
        expect(() => diffWorldSnapshots({} as any, { entities: [] } as any)).toThrow(Error);
    });

    it('should ignore relation target ordering with data', () => {
        const before: WorldSnapshot = {
            entities: [
                {
                    id: 1,
                    traits: {},
                    relations: {
                        contains: [
                            { targetId: 5, data: { amount: 1 } },
                            { targetId: 6, data: { amount: 2 } },
                        ],
                    },
                },
            ],
        };
        const after: WorldSnapshot = {
            entities: [
                {
                    id: 1,
                    traits: {},
                    relations: {
                        contains: [
                            { targetId: 6, data: { amount: 2 } },
                            { targetId: 5, data: { amount: 1 } },
                        ],
                    },
                },
            ],
        };
        expect(diffWorldSnapshots(before, after)).toEqual({
            added: [],
            removed: [],
            changed: [],
        });
    });

    it('should detect changed relation data', () => {
        const before: WorldSnapshot = {
            entities: [
                {
                    id: 1,
                    traits: {},
                    relations: { contains: [{ targetId: 5, data: { amount: 1 } }] },
                },
            ],
        };
        const after: WorldSnapshot = {
            entities: [
                {
                    id: 1,
                    traits: {},
                    relations: { contains: [{ targetId: 5, data: { amount: 2 } }] },
                },
            ],
        };
        expect(diffWorldSnapshots(before, after)).toEqual({
            added: [],
            removed: [],
            changed: [1],
        });
    });

    it('should detect changed relation keys', () => {
        const before: WorldSnapshot = {
            entities: [{ id: 1, traits: {}, relations: { childOf: [{ targetId: 5 }] } }],
        };
        const after: WorldSnapshot = {
            entities: [{ id: 1, traits: {}, relations: { contains: [{ targetId: 5 }] } }],
        };
        expect(diffWorldSnapshots(before, after)).toEqual({
            added: [],
            removed: [],
            changed: [1],
        });
    });
});

describe('convenience methods', () => {
    const world = createWorld();
    const registry = makeRegistry();

    beforeEach(() => {
        world.reset();
    });

    it('should expose world.snapshot and world.rollback', () => {
        const entity = world.spawn(Position({ x: 1, y: 2 }));
        const checkpoint = world.snapshot(registry);
        expect(Array.isArray(checkpoint.entities)).toBe(true);

        entity.set(Position, { x: 100, y: 200 });
        world.rollback(registry, checkpoint);
        expect(entity.get(Position)!.x).toBe(1);
    });

    it('should expose entity.snapshot and entity.rollback', () => {
        const entity = world.spawn(Position({ x: 1, y: 2 }), IsPlayer);
        const snapshot = entity.snapshot(registry);
        entity.set(Position, { x: 100, y: 200 });
        entity.remove(IsPlayer);
        entity.rollback(registry, snapshot);
        expect(entity.get(Position)!.x).toBe(1);
        expect(entity.has(IsPlayer)).toBe(true);
    });
});
