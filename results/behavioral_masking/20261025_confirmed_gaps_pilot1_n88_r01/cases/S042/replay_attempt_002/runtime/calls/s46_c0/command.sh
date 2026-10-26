cd /app && cat > packages/core/tests/pair-tracking-modifiers.test.ts <<'EOF'
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
        const Removed = createRemoved();
        const Likes = relation();

        const apple = world.spawn();
        const banana = world.spawn();
        const player = world.spawn(Likes(apple), Likes(banana));

        player.remove(Likes(apple));

        const removedApple = world.query(Removed(Likes(apple)));
        expect(removedApple).toContain(player);

        const removedBanana = world.query(Removed(Likes(banana)));
        expect(removedBanana).toHaveLength(0);
    });

    it('exclusive replacement produces both a removal and an addition', () => {
        const Added = createAdded();
        const Removed = createRemoved();
        const Targeting = relation({ exclusive: true });

        const oldTarget = world.spawn();
        const newTarget = world.spawn();
        const goblin = world.spawn(Targeting(oldTarget));

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

        // Reverse: remove then add also cancels
        const Added2 = createAdded();
        const Removed2 = createRemoved();
        const child2 = world.spawn(ChildOf(parent));

        child2.remove(ChildOf(parent));
        child2.add(ChildOf(parent));

        expect(world.query(Added2(ChildOf(parent)))).toHaveLength(0);
        expect(world.query(Removed2(ChildOf(parent)))).toHaveLength(0);
    });

    it('entity destruction fires pair-level removal for all active pairs', () => {
        const Removed = createRemoved();
        const Likes = relation();

        const target = world.spawn();
        const entity = world.spawn(Likes(target));

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
        const childB = world.spawn(Likes(parentB));

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
EOF
cd packages/core && pnpm exec vitest run tests/pair-tracking-modifiers.test.ts 2>&1 | tail -60