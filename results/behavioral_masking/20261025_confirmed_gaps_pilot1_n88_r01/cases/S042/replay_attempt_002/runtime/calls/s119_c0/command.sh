cd /app && cat > packages/core/tests/zz-or.test.ts <<'EOF'
import { describe, it, expect } from 'vitest';
import { createWorld, createAdded, relation, Or, getStore } from '/app/packages/core/src/index.ts';
describe('or debug', () => {
 it('x', () => {
  const world = createWorld(); world.init();
  const Added = createAdded();
  const Contains = relation({ store: { amount: 0 } });
  const a = world.spawn(); const b = world.spawn();
  const e1 = world.spawn(); const e2 = world.spawn();
  e1.add(Contains(a, { amount: 1 }));
  e2.add(Contains(b, { amount: 2 }));
  const mod = Or(Added(Contains(a)), Added(Contains(b)));
  console.log('mod pairs', mod.pairs, 'mod modifiers', mod.modifiers?.map(m=>m.pairs?.length));
  const q = world.query(mod);
  console.log('q length', q.length);
  q.readEach((s, e) => { console.log('state', s, 'eid', e.id()); });
  expect(1).toBe(1);
 });
});
EOF
cd packages/core && pnpm exec vitest run tests/zz-or.test.ts 2>&1 | tail -60
rm packages/core/tests/zz-or.test.ts