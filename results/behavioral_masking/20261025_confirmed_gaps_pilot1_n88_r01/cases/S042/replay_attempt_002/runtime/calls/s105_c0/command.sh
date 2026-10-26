cd /app && python3 - <<'PY'
p='packages/core/src/relation/tracking.ts'
s=open(p).read()
marker="""    for (const query of instance.trackingQueries) {
        const match = query.checkTracking("""
insert="""    for (const query of instance.trackingQueries) {
        console.log('UPDATE', eventType, 'map', canceledByTracker ? [...canceledByTracker.entries()] : 'none', 'query gids', query.trackingGroups.map(g=>g.id), 'entity', entity);
        const match = query.checkTracking("""
s=s.replace(marker, insert)
open(p,'w').write(s)

p='packages/core/src/query/utils/check-query-tracking.ts'
s=open(p).read()
marker="""        if (affected) {
            // Cross-event invalidation:"""
insert="""        if (affected && group.pairs && group.pairs.length > 0) {
            console.log('CQ', 'ev', eventType, 'gt', groupType, 'gl', groupLogic, 'gid', group.id, 'canceled', pairCanceledByTracker?.get(group.id), 'target', target);
        }
        if (affected) {
            // Cross-event invalidation:"""
s=s.replace(marker, insert)
open(p,'w').write(s)
print('logs added')
PY
cat > packages/core/tests/zz-debug.test.ts <<'EOF'
import { describe, it, expect } from 'vitest';
import { createWorld, createAdded, createRemoved, relation } from '/app/packages/core/src/index.ts';
describe('debug cancellation', () => {
 it('x', () => {
  const world = createWorld(); world.init();
  const Added = createAdded();
  const Removed = createRemoved();
  const ChildOf = relation();
  const parent = world.spawn();
  const child = world.spawn();
  expect(world.query(Added(ChildOf(parent)))).toHaveLength(0);
  expect(world.query(Removed(ChildOf(parent)))).toHaveLength(0);
  child.add(ChildOf(parent));
  console.log('--- after add');
  child.remove(ChildOf(parent));
  console.log('--- after remove, before query');
  expect(world.query(Added(ChildOf(parent)))).toHaveLength(0);
  expect(world.query(Removed(ChildOf(parent)))).toHaveLength(0);
 });
});
EOF
cd packages/core && pnpm exec vitest run tests/zz-debug.test.ts 2>&1 | tail -100
rm packages/core/tests/zz-debug.test.ts