cd /app && cat >> packages/core/tests/pair-tracking-modifiers.test.ts <<'EOF'

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
EOF
cd packages/core && pnpm exec vitest run tests/pair-tracking-modifiers.test.ts 2>&1 | tail -40