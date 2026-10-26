cd /app && cat >> packages/core/tests/pair-tracking-modifiers.test.ts <<'EOF'

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

        const seen = new Map<number, number>();
        world
            .query(Or(Added(Contains(targetA)), Added(Contains(targetB))))
            .readEach(([contains], entity) => {
                seen.set(entity.id(), (contains as { amount: number }).amount);
            });

        expect(seen.get(entityA.id())).toBe(1);
        expect(seen.get(entityB.id())).toBe(2);
    });
});
EOF
cd packages/core && pnpm exec vitest run tests/pair-tracking-modifiers.test.ts 2>&1 | tail -40