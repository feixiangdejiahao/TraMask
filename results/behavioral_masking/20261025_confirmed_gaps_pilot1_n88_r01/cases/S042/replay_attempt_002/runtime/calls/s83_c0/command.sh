cd /app && cat >> packages/core/tests/pair-tracking-modifiers.test.ts <<'EOF'

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
        const player = world.spawn(Likes(apple), Likes(banana));
        const Removed = createRemoved();

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
EOF
cd packages/core && pnpm exec vitest run tests/pair-tracking-modifiers.test.ts 2>&1 | tail -80