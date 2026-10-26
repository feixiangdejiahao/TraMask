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

describe('Pair tracking modifiers', () => {
    const world = createWorld();
    world.init();

    beforeEach(() => {
        world.reset();
    });

    it('detects non-first pair additions at pair level', () => {
        const Likes = relation();
        const Added = createAdded();

        const alice = world.spawn();
        const bob = world.spawn();
        const person = world.spawn();

        person.add(Likes(bob));
        // Drain trait-level Added (bob was the first pair).
        world.query(Added(Likes));
        world.query(Added(Likes(alice)));

        person.add(Likes(alice)); // non-first addition

        const q = world.query(Added(Likes(alice)));
        expect(q).toHaveLength(1);
        expect(q).toContain(person);

        // Trait-level Added does not fire for non-first additions.
        const traitLevel = world.query(Added(Likes));
        expect(traitLevel).toHaveLength(0);
    });

    it('detects non-last pair removals at pair level', () => {
        const Likes = relation();
        const Removed = createRemoved();

        const alice = world.spawn();
        const bob = world.spawn();
        const person = world.spawn(Likes(alice), Likes(bob));

        person.remove(Likes(alice)); // non-last removal

        const q = world.query(Removed(Likes(alice)));
        expect(q).toHaveLength(1);
        expect(q).toContain(person);

        // Trait-level Removed does not fire for non-last removals.
        const traitLevel = world.query(Removed(Likes));
        expect(traitLevel).toHaveLength(0);
    });

    it('wildcard target matches any pair', () => {
        const Likes = relation();
        const Removed = createRemoved();

        const apple = world.spawn();
        const banana = world.spawn();
        const person = world.spawn(Likes(apple), Likes(banana));

        person.remove(Likes(apple));

        const q = world.query(Removed(Likes('*')));
        expect(q).toHaveLength(1);
        expect(q).toContain(person);
    });

    it('exclusive replacement produces both a removal and an addition', () => {
        const Targeting = relation({ exclusive: true });
        const Added = createAdded();
        const Removed = createRemoved();

        const a = world.spawn();
        const b = world.spawn();
        const enemy = world.spawn(Targeting(a));

        // Drain initial pair events.
        world.query(Added(Targeting('*')));
        world.query(Removed(Targeting('*')));

        enemy.add(Targeting(b));

        const added = world.query(Added(Targeting(b)));
        const removed = world.query(Removed(Targeting(a)));
        expect(added).toContain(enemy);
        expect(removed).toContain(enemy);
    });

    it('opposite pair events on the same target cancel Added', () => {
        const Likes = relation();
        const Added = createAdded();
        const Removed = createRemoved();

        const alice = world.spawn();
        const person = world.spawn();

        person.add(Likes(alice));
        person.remove(Likes(alice));

        expect(world.query(Added(Likes(alice)))).toHaveLength(0);
        // A removal event did occur, so Removed still reports it.
        expect(world.query(Removed(Likes(alice)))).toHaveLength(1);
    });

    it('fires pair-level removal when an entity is destroyed', () => {
        const Likes = relation();
        const Removed = createRemoved();

        const alice = world.spawn();
        const person = world.spawn(Likes(alice), Likes('*'));

        person.destroy();

        const q = world.query(Removed(Likes(alice)));
        expect(q).toHaveLength(1);
        expect(q).toContain(person);
    });

    it('composes with Or', () => {
        const Likes = relation();
        const Fears = relation();
        const Added = createAdded();

        const apple = world.spawn();
        const ghost = world.spawn();
        const person = world.spawn();

        person.add(Likes(apple));

        const q = world.query(Or(Added(Likes(apple)), Added(Fears(ghost))));
        expect(q).toHaveLength(1);
        expect(q).toContain(person);

        // Drain then add the other pair.
        world.query(Or(Added(Likes(apple)), Added(Fears(ghost))));
        person.add(Fears(ghost));
        const q2 = world.query(Or(Added(Likes(apple)), Added(Fears(ghost))));
        expect(q2).toContain(person);
    });

    it('different pair targets produce distinct cached queries', () => {
        const Likes = relation();
        const Added = createAdded();

        const alice = world.spawn();
        const bob = world.spawn();

        const qa = world.query(Added(Likes(alice)));
        const qb = world.query(Added(Likes(bob)));

        expect(qa).not.toBe(qb);

        // Distinct pair targets produce distinct cached query instances.
        const ctx = world[$internal];
        const hashes = [...ctx.queriesHashMap.keys()];
        expect(hashes.length).toBeGreaterThanOrEqual(2);

        // Sanity: each query only returns its own target's additions.
        world.query(Added(Likes(alice)));
        world.query(Added(Likes(bob)));
        const pa = world.spawn(Likes(alice));
        const pb = world.spawn(Likes(bob));
        expect(world.query(Added(Likes(alice)))).toContain(pa);
        expect(world.query(Added(Likes(bob)))).toContain(pb);
        world.query(Added(Likes(alice))).forEach((e) => expect(e).toBe(pa));
        world.query(Added(Likes(bob))).forEach((e) => expect(e).toBe(pb));
    });

    it('combines pair modifiers with regular trait parameters', () => {
        const Likes = relation();
        const Position = trait({ x: 0 });
        const Added = createAdded();

        const alice = world.spawn();
        const withPosition = world.spawn(Position);
        const withoutPosition = world.spawn();

        withPosition.add(Likes(alice));
        withoutPosition.add(Likes(alice));

        const q = world.query(Added(Likes(alice)), Position);
        expect(q).toHaveLength(1);
        expect(q).toContain(withPosition);
        expect(q).not.toContain(withoutPosition);
    });

    it('entity.changed accepts a RelationPair for manual pair-level change signaling', () => {
        const Likes = relation({ store: { amount: 0 } });
        const Changed = createChanged();

        const alice = world.spawn();
        const bob = world.spawn();
        const person = world.spawn(Likes(alice, { amount: 1 }), Likes(bob, { amount: 2 }));

        // Drain.
        world.query(Changed(Likes(alice)));
        world.query(Changed(Likes(bob)));

        person.changed(Likes(alice));

        const changedAlice = world.query(Changed(Likes(alice)));
        const changedBob = world.query(Changed(Likes(bob)));
        expect(changedAlice).toContain(person);
        expect(changedBob).toHaveLength(0);
    });

    it('query result iteration resolves per-target relation data', () => {
        const Contains = relation({ store: { amount: 0 } });
        const Added = createAdded();
        const Removed = createRemoved();

        const gold = world.spawn();
        const inventory = world.spawn();

        inventory.add(Contains(gold, { amount: 42 }));

        let addedData: any;
        world.query(Added(Contains(gold))).readEach(([contains]) => {
            addedData = contains;
        });
        expect(addedData).toEqual({ amount: 42 });

        // Drain and remove.
        world.query(Added(Contains(gold)));
        inventory.remove(Contains(gold));

        let removedData: any;
        const removedQuery = world.query(Removed(Contains(gold)));
        expect(removedQuery).toHaveLength(1);
        removedQuery.readEach(([contains]) => {
            removedData = contains;
        });
        expect(removedData).toEqual({ amount: 42 });
    });

    it('tracking modifiers are long-lived and reused across world resets', () => {
        const Likes = relation();
        const Added = createAdded();

        const alice = world.spawn();
        world.reset();

        const person = world.spawn();
        person.add(Likes(alice));

        const q = world.query(Added(Likes(alice)));
        expect(q).toHaveLength(1);
        expect(q).toContain(person);
    });

    it('tracks Changed on a relation pair specifically', () => {
        const Likes = relation({ store: { amount: 0 } });
        const Changed = createChanged();

        const alice = world.spawn();
        const bob = world.spawn();
        const person = world.spawn(Likes(alice, { amount: 1 }), Likes(bob, { amount: 2 }));

        world.query(Changed(Likes(alice)));
        world.query(Changed(Likes(bob)));

        person.set(Likes(alice), { amount: 10 });

        const changedAlice = world.query(Changed(Likes(alice)));
        const changedBob = world.query(Changed(Likes(bob)));
        expect(changedAlice).toContain(person);
        expect(changedBob).toHaveLength(0);
    });
});
