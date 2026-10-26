cd /app && cat >> packages/core/tests/pair-tracking-modifiers.test.ts <<'EOF'

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
EOF
cd packages/core && pnpm exec vitest run tests/pair-tracking-modifiers.test.ts 2>&1 | tail -40