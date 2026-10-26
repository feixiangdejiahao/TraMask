cd /app && python3 - <<'PY'
p='packages/core/tests/pair-tracking-modifiers.test.ts'
s=open(p).read()
# Non-last removals: create Removed after first pair exists
s=s.replace("""    it('detects non-last pair removals', () => {
        const Removed = createRemoved();
        const Likes = relation();

        const apple = world.spawn();
        const banana = world.spawn();
        const player = world.spawn(Likes(apple), Likes(banana));

        player.remove(Likes(apple));""", """    it('detects non-last pair removals', () => {
        const Likes = relation();

        const apple = world.spawn();
        const banana = world.spawn();
        const player = world.spawn(Likes(apple), Likes(banana));

        // Create the factory after the initial pair exists so removal isn't
        // cancelled by an in-window addition.
        const Removed = createRemoved();

        player.remove(Likes(apple));""")
# Exclusive replacement: create factories after initial target exists
s=s.replace("""    it('exclusive replacement produces both a removal and an addition', () => {
        const Added = createAdded();
        const Removed = createRemoved();
        const Targeting = relation({ exclusive: true });

        const oldTarget = world.spawn();
        const newTarget = world.spawn();
        const goblin = world.spawn(Targeting(oldTarget));

        goblin.add(Targeting(newTarget));""", """    it('exclusive replacement produces both a removal and an addition', () => {
        const Targeting = relation({ exclusive: true });

        const oldTarget = world.spawn();
        const newTarget = world.spawn();
        const goblin = world.spawn(Targeting(oldTarget));

        // Create factories after the initial pair exists so the old target is
        // in the snapshot rather than an in-window addition.
        const Added = createAdded();
        const Removed = createRemoved();

        goblin.add(Targeting(newTarget));""")
# Reverse cancellation: create factories after initial pair exists
s=s.replace("""        // Reverse: remove then add also cancels
        const Added2 = createAdded();
        const Removed2 = createRemoved();
        const child2 = world.spawn(ChildOf(parent));

        child2.remove(ChildOf(parent));
        child2.add(ChildOf(parent));""", """        // Reverse: remove then add also cancels (factory after initial pair exists)
        const child2 = world.spawn(ChildOf(parent));
        const Added2 = createAdded();
        const Removed2 = createRemoved();

        child2.remove(ChildOf(parent));
        child2.add(ChildOf(parent));""")
# Destruction: create Removed after entity exists
s=s.replace("""    it('entity destruction fires pair-level removal for all active pairs', () => {
        const Removed = createRemoved();
        const Likes = relation();

        const target = world.spawn();
        const entity = world.spawn(Likes(target));

        entity.destroy();""", """    it('entity destruction fires pair-level removal for all active pairs', () => {
        const Likes = relation();

        const target = world.spawn();
        const entity = world.spawn(Likes(target));

        // Factory created after the pair exists so destruction is a real removal.
        const Removed = createRemoved();

        entity.destroy();""")
open(p,'w').write(s)
print('tests updated')
PY
cd packages/core && pnpm exec vitest run tests/pair-tracking-modifiers.test.ts 2>&1 | tail -60