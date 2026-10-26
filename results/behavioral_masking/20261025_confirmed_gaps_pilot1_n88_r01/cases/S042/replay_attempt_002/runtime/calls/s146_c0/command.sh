cd /app && cat > packages/core/tests/zz-removed.test.ts <<'EOF'
import { describe, it } from 'vitest';
import { createWorld, createRemoved, relation, getStore } from '/app/packages/core/src/index.ts';
describe('removed debug', () => {
 it('x', () => {
  const world = createWorld(); world.init();
  const Removed = createRemoved();
  const Contains = relation({ store: { amount: 0 } });
  const inventory = world.spawn();
  const gold = world.spawn();
  inventory.add(Contains(gold, { amount: 42 }));
  console.log('store before', getStore(world, Contains[$internal].trait));
  inventory.remove(Contains(gold));
  console.log('store after', getStore(world, Contains[$internal].trait));
  world.query(Removed(Contains), Contains(gold)).updateEach(([contains], entity) => {
    console.log('contains', contains);
  });
 });
});
EOF
cd packages/core && pnpm exec vitest run tests/zz-removed.test.ts 2>&1 | tail -50
rm packages/core/tests/zz-removed.test.ts