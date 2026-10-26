import { beforeEach, describe, expect, it } from 'vitest';
import { createWorld, relation, trait, universe, type Entity } from '../src';

describe('deferred command buffer', () => {
    const A = trait({ value: 0 });
    const B = trait({ value: 0 });
    const Likes = relation();
    const ChildOf = relation({ autoDestroy: 'source' });
    const Contains = relation({ autoDestroy: 'target' });

    beforeEach(() => {
        universe.reset();
    });

    it('spawns entities on flush', () => {
        const world = createWorld();
        const entity = world.deferred.spawn(A({ value: 1 }));

        expect(entity.has(A)).toBe(true);
        expect(entity.get(A)!.value).toBe(1);
        expect(world.has(entity)).toBe(true);
        expect(world.entities).not.toContain(entity);

        world.deferred.flush();

        expect(world.entities).toContain(entity);
        expect(entity.get(A)!.value).toBe(1);
    });

    it('adds and removes traits', () => {
        const world = createWorld();
        const entity = world.spawn();

        world.deferred.add(entity, A({ value: 5 }));
        expect(entity.has(A)).toBe(true);
        expect(entity.get(A)!.value).toBe(5);

        world.deferred.flush();
        expect(world.query(A)).toContain(entity);

        world.deferred.remove(entity, A);
        expect(entity.has(A)).toBe(false);
        world.deferred.flush();
        expect(world.query(A)).not.toContain(entity);
    });

    it('destroys entities on flush and nullifies spawn-destroy', () => {
        const world = createWorld();
        const entity = world.spawn(A);
        const spawned = world.deferred.spawn(A({ value: 3 }));

        world.deferred.destroy(entity);
        world.deferred.destroy(spawned);

        expect(entity.isAlive()).toBe(false);
        expect(spawned.isAlive()).toBe(false);

        world.deferred.flush();

        expect(world.has(entity)).toBe(false);
        expect(world.has(spawned)).toBe(false);
    });

    it('later values for the same trait replace earlier ones', () => {
        const world = createWorld();
        const entity = world.deferred.spawn(A({ value: 1 }));
        world.deferred.add(entity, A({ value: 2 }));

        expect(entity.get(A)!.value).toBe(2);

        world.deferred.flush();
        expect(entity.get(A)!.value).toBe(2);
    });

    it('addExclusive replaces pairs and wildcard clears them', () => {
        const world = createWorld();
        const subject = world.spawn();
        const targetA = world.spawn();
        const targetB = world.spawn();
        const targetC = world.spawn();

        world.deferred.add(subject, Likes(targetA), Likes(targetB));
        world.deferred.addExclusive(subject, Likes(targetC));

        expect(subject.has(Likes(targetA))).toBe(false);
        expect(subject.has(Likes(targetB))).toBe(false);
        expect(subject.has(Likes(targetC))).toBe(true);
        expect(subject.targetsFor(Likes)).toEqual([targetC]);

        world.deferred.flush();
        expect(subject.targetsFor(Likes)).toEqual([targetC]);

        world.deferred.addExclusive(subject, Likes, '*');
        world.deferred.flush();
        expect(subject.targetsFor(Likes)).toEqual([]);
    });

    it('throws when the world entity is destroyed on flush', () => {
        const world = createWorld();
        const internal = (world as any)[Symbol.for('koota.internal')];
        world.deferred.destroy(internal.worldEntity as Entity);
        expect(() => world.deferred.flush()).toThrow();
    });

    it('silently skips commands on destroyed entities', () => {
        const world = createWorld();
        const adds: number[] = [];
        world.onAdd(A, (entity) => adds.push(entity));

        const entity = world.spawn();
        world.deferred.destroy(entity);
        world.deferred.add(entity, A({ value: 1 }));
        world.deferred.flush();

        expect(adds).toEqual([]);
        expect(world.has(entity)).toBe(false);
    });

    it('fires one remove event per relation pair when an entity is destroyed', () => {
        const world = createWorld();
        const removes: Array<{ entity: number; target: number }> = [];
        world.onRemove(Likes, (entity: any, target: any) => removes.push({ entity, target }));

        const subject = world.spawn();
        const target = world.spawn();
        subject.add(Likes(target));

        world.deferred.destroy(subject);
        world.deferred.flush();

        expect(removes).toHaveLength(1);
        expect(removes[0]!.target).toBe(target);
    });

    it('fires subscriptions once per pair based on state difference', () => {
        const world = createWorld();
        const adds: Array<{ entity: number; target: number }> = [];
        const removes: Array<{ entity: number; target: number }> = [];
        world.onAdd(Likes, (entity: any, target: any) => adds.push({ entity, target }));
        world.onRemove(Likes, (entity: any, target: any) => removes.push({ entity, target }));

        const subject = world.spawn();
        const targetA = world.spawn();
        const targetB = world.spawn();
        const targetC = world.spawn();

        world.deferred.add(subject, Likes(targetA), Likes(targetB));
        world.deferred.flush();
        expect(adds).toHaveLength(2);
        expect(removes).toHaveLength(0);

        world.deferred.remove(subject, Likes(targetA));
        world.deferred.flush();
        expect(removes).toHaveLength(1);
        expect(removes[0]!.target).toBe(targetA);

        world.deferred.addExclusive(subject, Likes(targetC));
        world.deferred.flush();
        expect(adds).toHaveLength(3);
        expect(removes).toHaveLength(2);
        expect(removes[1]!.target).toBe(targetB);
    });

    it('flushes on updateEach exit', () => {
        const world = createWorld();
        world.spawn(A({ value: 1 }));
        let spawned: Entity | undefined;

        world.query(A).updateEach(() => {
            spawned = world.deferred.spawn(B);
            expect(world.query(B)).not.toContain(spawned);
        });

        expect(world.has(spawned!)).toBe(true);
        expect(world.query(B)).toContain(spawned);
    });

    it('flushes pending commands on non-deferred mutation of the same entity', () => {
        const world = createWorld();
        const entity = world.spawn();
        world.deferred.add(entity, A({ value: 1 }));

        entity.add(B);

        expect(entity.has(A)).toBe(true);
        expect(world.query(A)).toContain(entity);
    });

    it('preserves outer buffers when inner scopes flush', () => {
        const world = createWorld();
        world.spawn(A({ value: 1 }));
        world.spawn(B);

        let outerSpawned: Entity | undefined;
        let innerSpawned: Entity | undefined;

        world.query(A).updateEach(() => {
            outerSpawned = world.deferred.spawn(B);
            world.query(B).updateEach(() => {
                innerSpawned = world.deferred.spawn(A({ value: 2 }));
            });

            expect(world.has(innerSpawned!)).toBe(true);
            expect(world.query(B)).not.toContain(outerSpawned);
        });

        expect(world.query(B)).toContain(outerSpawned);
    });

    it('cascades autoDestroy respecting nullification', () => {
        const world = createWorld();
        const parent = world.spawn();
        const child = world.spawn(ChildOf(parent));
        const spawnedChild = world.deferred.spawn(ChildOf(parent));

        world.deferred.destroy(parent);
        world.deferred.flush();

        expect(world.has(parent)).toBe(false);
        expect(world.has(child)).toBe(false);
        expect(world.has(spawnedChild)).toBe(false);
    });

    it('cascades autoDestroy target and respects explicit removal', () => {
        const world = createWorld();
        const container = world.spawn();
        const item = world.spawn();
        container.add(Contains(item));
        world.deferred.destroy(container);
        world.deferred.flush();
        expect(world.has(item)).toBe(false);

        const container2 = world.spawn();
        const item2 = world.spawn();
        container2.add(Contains(item2));
        world.deferred.remove(container2, Contains(item2));
        world.deferred.destroy(container2);
        world.deferred.flush();
        expect(world.has(item2)).toBe(true);
    });
});
