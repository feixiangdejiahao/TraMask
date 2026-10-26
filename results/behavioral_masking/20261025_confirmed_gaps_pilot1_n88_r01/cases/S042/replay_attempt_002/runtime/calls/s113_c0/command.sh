cd /app && cat >> packages/core/tests/pair-tracking-modifiers.test.ts <<'EOF'

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
EOF
cd packages/core && pnpm exec vitest run tests/pair-tracking-modifiers.test.ts 2>&1 | tail -60