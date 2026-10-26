cd /app && cat >> packages/core/tests/pair-tracking-modifiers.test.ts <<'EOF'

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
EOF
cd packages/core && pnpm exec vitest run tests/pair-tracking-modifiers.test.ts 2>&1 | tail -35