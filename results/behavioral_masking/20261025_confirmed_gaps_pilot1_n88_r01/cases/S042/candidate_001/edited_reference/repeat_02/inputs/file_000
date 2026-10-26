import { beforeEach, describe, expect, it } from 'vitest';
import {
    $internal,
    createAdded,
    createChanged,
    createRemoved,
    createWorld,
    Or,
    relation,
    trait,
} from '../src';

describe('pair tracking modifiers', () => {
    const world = createWorld();
    world.init();

    beforeEach(() => {
        world.reset();
    });

    it('accepts relation pairs with a specific target', () => {
        const Added = createAdded();
        const ChildOf = relation();

        const parent = world.spawn();
        const child = world.spawn();

        expect(world.query(Added(ChildOf(parent)))).toHaveLength(0);

        child.add(ChildOf(parent));
        const entities = world.query(Added(ChildOf(parent)));
        expect(entities).toContain(child);
    });

    it('wildcard target acts as a wildcard for any pair', () => {
        const Added = createAdded();
        const ChildOf = relation();

        const parentA = world.spawn();
        const parentB = world.spawn();
        const childA = world.spawn();
        const childB = world.spawn();

        childA.add(ChildOf(parentA));
        childB.add(ChildOf(parentB));

        const entities = world.query(Added(ChildOf('*')));
        expect(entities).toContain(childA);
        expect(entities).toContain(childB);
    });

    it('detects non-first pair additions', () => {
        const Added = createAdded();
        const Likes = relation();

        const apple = world.spawn();
        const banana = world.spawn();
        const player = world.spawn(Likes(apple));

        expect(world.query(Added(Likes(banana)))).toHaveLength(0);

        player.add(Likes(banana));
        const entities = world.query(Added(Likes(banana)));
        expect(entities).toContain(player);
    });

    it('detects non-last pair removals', () => {
        const Likes = relation();

        const apple = world.spawn();
        const banana = world.spawn();
        const player = world.spawn(Likes(apple), Likes(banana));

        // Create the factory after the initial pair exists so removal isn't
        // cancelled by an in-window addition.
        const Removed = createRemoved();

        player.remove(Likes(apple));

        const removedApple = world.query(Removed(Likes(apple)));
        expect(removedApple).toContain(player);

        const removedBanana = world.query(Removed(Likes(banana)));
        expect(removedBanana).toHaveLength(0);
    });

    it('exclusive replacement produces both a removal and an addition', () => {
        const Targeting = relation({ exclusive: true });

        const oldTarget = world.spawn();
        const newTarget = world.spawn();
        const goblin = world.spawn(Targeting(oldTarget));

        // Create factories after the initial pair exists so the old target is
        // in the snapshot rather than an in-window addition.
        const Added = createAdded();
        const Removed = createRemoved();

        goblin.add(Targeting(newTarget));

        const added = world.query(Added(Targeting(newTarget)));
        const removed = world.query(Removed(Targeting(oldTarget)));

        expect(added).toContain(goblin);
        expect(removed).toContain(goblin);
    });

    it('factories are long-lived and reused across world resets', () => {
        const Added = createAdded();
        const T = trait();

        world.reset();

        const entity = world.spawn();
        entity.add(T);

        const entities = world.query(Added(T));
        expect(entities).toContain(entity);
    });

    it('opposite pair events on the same target cancel within an observation window', () => {
        const Added = createAdded();
        const Removed = createRemoved();
        const ChildOf = relation();

        const parent = world.spawn();
        const child = world.spawn();

        child.add(ChildOf(parent));
        child.remove(ChildOf(parent));

        expect(world.query(Added(ChildOf(parent)))).toHaveLength(0);
        expect(world.query(Removed(ChildOf(parent)))).toHaveLength(0);

        // Reverse: remove then add also cancels (factory after initial pair exists)
        const child2 = world.spawn(ChildOf(parent));
        const Added2 = createAdded();
        const Removed2 = createRemoved();

        child2.remove(ChildOf(parent));
        child2.add(ChildOf(parent));

        expect(world.query(Added2(ChildOf(parent)))).toHaveLength(0);
        expect(world.query(Removed2(ChildOf(parent)))).toHaveLength(0);
    });

    it('entity destruction fires pair-level removal for all active pairs', () => {
        const Likes = relation();

        const target = world.spawn();
        const entity = world.spawn(Likes(target));

        // Factory created after the pair exists so destruction is a real removal.
        const Removed = createRemoved();

        entity.destroy();

        const removed = world.query(Removed(Likes(target)));
        expect(removed).toContain(entity);
    });

    it('pair modifiers compose with Or', () => {
        const Added = createAdded();
        const Likes = relation();

        const parentA = world.spawn();
        const parentB = world.spawn();
        const childA = world.spawn();
        const childB = world.spawn();

        childA.add(Likes(parentA));
        childB.add(Likes(parentB));

        const entities = world.query(Or(Added(Likes(parentA)), Added(Likes(parentB))));
        expect(entities).toContain(childA);
        expect(entities).toContain(childB);
    });

    it('different pair targets produce distinct cached queries', () => {
        const Added = createAdded();
        const Likes = relation();

        const parentA = world.spawn();
        const parentB = world.spawn();

        world.query(Added(Likes(parentA)));
        const sizeAfterA = world[$internal].queriesHashMap.size;

        world.query(Added(Likes(parentB)));
        const sizeAfterB = world[$internal].queriesHashMap.size;

        expect(sizeAfterB).toBeGreaterThan(sizeAfterA);

        world.query(Added(Likes(parentA)));
        expect(world[$internal].queriesHashMap.size).toBe(sizeAfterB);
    });

    it('pair modifiers combine with regular trait parameters', () => {
        const Added = createAdded();
        const Likes = relation();
        const Foo = trait();

        const target = world.spawn();
        const entityWithFoo = world.spawn(Foo);
        const entityWithoutFoo = world.spawn();

        entityWithFoo.add(Likes(target));
        entityWithoutFoo.add(Likes(target));

        const entities = world.query(Added(Likes(target)), Foo);
        expect(entities).toContain(entityWithFoo);
        expect(entities).not.toContain(entityWithoutFoo);
    });

    it('Changed accepts relation pairs and filters by target', () => {
        const Changed = createChanged();
        const Likes = relation({ store: { amount: 0 } });

        const parentA = world.spawn();
        const parentB = world.spawn();
        const childA = world.spawn(Likes(parentA));
        world.spawn(Likes(parentB));

        childA.set(Likes(parentA), { amount: 1 });

        const changedA = world.query(Changed(Likes(parentA)));
        expect(changedA).toContain(childA);

        const changedB = world.query(Changed(Likes(parentB)));
        expect(changedB).toHaveLength(0);
    });

    it('entity.changed accepts a RelationPair', () => {
        const Changed = createChanged();
        const Likes = relation({ store: { amount: 0 } });

        const parent = world.spawn();
        const child = world.spawn(Likes(parent));

        child.changed(Likes(parent));

        const changed = world.query(Changed(Likes(parent)));
        expect(changed).toContain(child);
    });

    it('query result iteration resolves per-target relation data', () => {
        const Added = createAdded();
        const Contains = relation({ store: { amount: 0 } });

        const gold = world.spawn();
        const silver = world.spawn();
        const inventory = world.spawn();

        inventory.add(Contains(gold, { amount: 5 }));
        inventory.add(Contains(silver, { amount: 9 }));

        world.query(Added(Contains(gold))).readEach(([contains], entity) => {
            expect(entity).toBe(inventory);
            expect(contains).toHaveProperty('amount', 5);
        });
    });

    it('updateEach writes to the specific pair target', () => {
        const Added = createAdded();
        const Contains = relation({ store: { amount: 0 } });

        const gold = world.spawn();
        const silver = world.spawn();
        const inventory = world.spawn();

        inventory.add(Contains(gold, { amount: 5 }));
        inventory.add(Contains(silver, { amount: 9 }));

        world.query(Added(Contains(gold))).updateEach(([contains]) => {
            contains.amount = 7;
        });

        expect(inventory.get(Contains(gold))!.amount).toBe(7);
        expect(inventory.get(Contains(silver))!.amount).toBe(9);
    });
});

describe('pair tracking modifiers incremental paths', () => {
    const world = createWorld();
    world.init();

    beforeEach(() => {
        world.reset();
    });

    it('Removed pair works when the query is created before the removal', () => {
        const Likes = relation();
        const apple = world.spawn();
        const banana = world.spawn();
        const Removed = createRemoved();
        const player = world.spawn(Likes(apple), Likes(banana));

        expect(world.query(Removed(Likes(apple)))).toHaveLength(0);

        player.remove(Likes(apple));

        expect(world.query(Removed(Likes(apple)))).toContain(player);
    });

    it('Changed pair works when the query is created before the change', () => {
        const Likes = relation({ store: { amount: 0 } });
        const parent = world.spawn();
        const child = world.spawn(Likes(parent));
        const Changed = createChanged();

        expect(world.query(Changed(Likes(parent)))).toHaveLength(0);

        child.set(Likes(parent), { amount: 2 });

        expect(world.query(Changed(Likes(parent)))).toContain(child);
    });

    it('exclusive replacement works when queries are created before replacement', () => {
        const Targeting = relation({ exclusive: true });
        const oldTarget = world.spawn();
        const newTarget = world.spawn();
        const goblin = world.spawn(Targeting(oldTarget));
        const Added = createAdded();
        const Removed = createRemoved();

        expect(world.query(Added(Targeting(newTarget)))).toHaveLength(0);
        expect(world.query(Removed(Targeting(oldTarget)))).toHaveLength(0);

        goblin.add(Targeting(newTarget));

        expect(world.query(Added(Targeting(newTarget)))).toContain(goblin);
        expect(world.query(Removed(Targeting(oldTarget)))).toContain(goblin);
    });

    it('cancellation works when queries are created before opposite events', () => {
        const Added = createAdded();
        const Removed = createRemoved();
        const ChildOf = relation();
        const parent = world.spawn();
        const child = world.spawn();

        expect(world.query(Added(ChildOf(parent)))).toHaveLength(0);
        expect(world.query(Removed(ChildOf(parent)))).toHaveLength(0);

        child.add(ChildOf(parent));
        child.remove(ChildOf(parent));

        expect(world.query(Added(ChildOf(parent)))).toHaveLength(0);
        expect(world.query(Removed(ChildOf(parent)))).toHaveLength(0);
    });

    it('destruction works when query is created before destruction', () => {
        const Likes = relation();
        const target = world.spawn();
        const entity = world.spawn(Likes(target));
        const Removed = createRemoved();

        expect(world.query(Removed(Likes(target)))).toHaveLength(0);

        entity.destroy();

        expect(world.query(Removed(Likes(target)))).toContain(entity);
    });
});

describe('pair tracking modifiers edge cases', () => {
    const world = createWorld();
    world.init();

    beforeEach(() => {
        world.reset();
    });

    it('destruction fires pair-level removal for every active pair', () => {
        const Likes = relation();
        const targetA = world.spawn();
        const targetB = world.spawn();
        const entity = world.spawn(Likes(targetA), Likes(targetB));
        const Removed = createRemoved();

        entity.destroy();

        expect(world.query(Removed(Likes(targetA)))).toContain(entity);
        expect(world.query(Removed(Likes(targetB)))).toContain(entity);
    });

    it('wildcard removed matches any removed pair', () => {
        const Likes = relation();
        const targetA = world.spawn();
        const targetB = world.spawn();
        const entityA = world.spawn(Likes(targetA));
        const entityB = world.spawn(Likes(targetB));
        const Removed = createRemoved();

        entityA.remove(Likes(targetA));
        entityB.remove(Likes(targetB));

        const removed = world.query(Removed(Likes('*')));
        expect(removed).toContain(entityA);
        expect(removed).toContain(entityB);
    });

    it('Or composes pair modifiers with regular tracking modifiers', () => {
        const Added = createAdded();
        const Likes = relation();
        const Foo = trait();
        const target = world.spawn();
        const entityA = world.spawn();
        const entityB = world.spawn();

        entityA.add(Likes(target));
        entityB.add(Foo);

        const entities = world.query(Or(Added(Likes(target)), Added(Foo)));
        expect(entities).toContain(entityA);
        expect(entities).toContain(entityB);
    });

    it('pair query created after events is populated from accumulated state', () => {
        const Added = createAdded();
        const Likes = relation();
        const target = world.spawn();
        const entity = world.spawn();
        entity.add(Likes(target));

        // First query drains the event.
        expect(world.query(Added(Likes(target)))).toContain(entity);
        // A second query has no new events.
        expect(world.query(Added(Likes(target)))).toHaveLength(0);

        const targetB = world.spawn();
        const entityB = world.spawn();
        entityB.add(Likes(targetB));
        expect(world.query(Added(Likes(targetB)))).toContain(entityB);
    });
});

describe('pair tracking modifiers query result with Or', () => {
    const world = createWorld();
    world.init();

    beforeEach(() => {
        world.reset();
    });

    it('readEach resolves per-target data through Or', () => {
        const Added = createAdded();
        const Contains = relation({ store: { amount: 0 } });
        const targetA = world.spawn();
        const targetB = world.spawn();
        const entityA = world.spawn();
        const entityB = world.spawn();
        entityA.add(Contains(targetA, { amount: 1 }));
        entityB.add(Contains(targetB, { amount: 2 }));

        const seen = new Map<number, number | undefined>();
        world
            .query(Or(Added(Contains(targetA)), Added(Contains(targetB))))
            .readEach(([containsA, containsB], entity) => {
                const amount =
                    (containsA as { amount?: number } | undefined)?.amount ??
                    (containsB as { amount?: number } | undefined)?.amount;
                seen.set(entity.id(), amount);
            });

        expect(seen.get(entityA.id())).toBe(1);
        expect(seen.get(entityB.id())).toBe(2);
    });
});

describe('pair tracking modifiers additional', () => {
    const world = createWorld();
    world.init();

    beforeEach(() => {
        world.reset();
    });

    it('a single modifier can combine a pair and a regular trait with AND', () => {
        const Added = createAdded();
        const Likes = relation();
        const Foo = trait();
        const target = world.spawn();
        const withFoo = world.spawn(Foo);
        const withoutFoo = world.spawn();

        withFoo.add(Likes(target));
        withoutFoo.add(Likes(target));

        const entities = world.query(Added(Likes(target), Foo));
        expect(entities).toContain(withFoo);
        expect(entities).not.toContain(withoutFoo);
    });

    it('destroying a target fires pair-level removal on its sources', () => {
        const Likes = relation();
        const target = world.spawn();
        const source = world.spawn(Likes(target));
        const Removed = createRemoved();

        target.destroy();

        const removed = world.query(Removed(Likes(target)));
        expect(removed).toContain(source);
    });
});

describe('pair tracking modifiers hash with Or', () => {
    const world = createWorld();
    world.init();

    beforeEach(() => {
        world.reset();
    });

    it('Or pair queries with different targets have distinct hashes', () => {
        const Added = createAdded();
        const Likes = relation();
        const parentA = world.spawn();
        const parentB = world.spawn();

        world.query(Or(Added(Likes(parentA)), Added(Likes(parentA))));
        const sizeA = world[$internal].queriesHashMap.size;

        world.query(Or(Added(Likes(parentA)), Added(Likes(parentB))));
        const sizeB = world[$internal].queriesHashMap.size;

        expect(sizeB).toBeGreaterThan(sizeA);
    });
});

describe('pair tracking modifiers across reset', () => {
    const world = createWorld();
    world.init();

    it('pair factories keep working after reset', () => {
        const Added = createAdded();
        const Likes = relation();
        const parent = world.spawn();
        const child = world.spawn();
        child.add(Likes(parent));

        world.reset();

        const parent2 = world.spawn();
        const child2 = world.spawn();
        child2.add(Likes(parent2));

        const entities = world.query(Added(Likes(parent2)));
        expect(entities).toContain(child2);
    });
});
