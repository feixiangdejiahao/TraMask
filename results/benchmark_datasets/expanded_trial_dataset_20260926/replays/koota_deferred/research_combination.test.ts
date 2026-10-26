// Retrospective witness. Candidate source is unmodified; no reference patch.
import { beforeEach, expect, it } from 'vitest';
import { createWorld, trait, universe } from '../src';

beforeEach(() => universe.reset());

it('control: complete explicit payload is visible before flush', () => {
    const V = trait({ vx: 0, vy: 0 });
    const world = createWorld();
    const e = world.spawn();
    world.deferred.add(e, V({ vx: 100, vy: 9 }));
    expect(e.get(V)).toEqual({ vx: 100, vy: 9 });
});

it('control: fully omitted payload exposes schema defaults before flush', () => {
    const V = trait({ vx: 0, vy: 0 });
    const world = createWorld();
    const e = world.spawn();
    world.deferred.add(e, V());
    expect(e.get(V)).toEqual({ vx: 0, vy: 0 });
});

it('control: partial payload is completed by defaults after flush', () => {
    const V = trait({ vx: 0, vy: 0 });
    const world = createWorld();
    const e = world.spawn();
    world.deferred.add(e, V({ vx: 100 }));
    world.deferred.flush();
    expect(e.get(V)).toEqual({ vx: 100, vy: 0 });
});

it('combination: partial payload must expose omitted default before flush', () => {
    const V = trait({ vx: 0, vy: 0 });
    const world = createWorld();
    const e = world.spawn();
    world.deferred.add(e, V({ vx: 100 }));
    expect(e.get(V)).toEqual({ vx: 100, vy: 0 });
});
