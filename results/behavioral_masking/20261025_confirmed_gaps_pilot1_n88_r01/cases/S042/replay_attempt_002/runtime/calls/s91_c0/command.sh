cd /app && cp packages/core/src/relation/tracking.ts /tmp/tracking.bak && python3 - <<'PY'
p='packages/core/src/relation/tracking.ts'
s=open(p).read()
s=s.replace("""    for (const query of instance.trackingQueries) {
        const match = query.checkTracking(
            world,
            entity,
            eventType,
            generationId,
            bitflag,
            target,
            canceled
        );
        if (match) query.add(entity);
        else query.remove(world, entity);
    }
}""", """    for (const query of instance.trackingQueries) {
        console.log('PAIR-UPDATE', eventType, 'canceled', canceled, 'query hash', query.hash, 'groups', query.trackingGroups.map(g=>({type:g.type, logic:g.logic, pairs:g.pairs?.map(p=>p[$internal].target)})));
        const match = query.checkTracking(
            world,
            entity,
            eventType,
            generationId,
            bitflag,
            target,
            canceled
        );
        console.log('  match', match, 'entity', entity);
        if (match) query.add(entity);
        else query.remove(world, entity);
    }
}""")
# import $internal for pair target logging
if "import { $internal } from '../common';" not in s:
    s="import { $internal } from '../common';\n"+s
open(p,'w').write(s)
print('log added')
PY
cat > /tmp/debug_incremental.test.ts <<'EOF'
import { describe, it, expect } from 'vitest';
import { createWorld, createRemoved, relation } from '/app/packages/core/src/index.ts';
describe('debug', () => {
 it('x', () => {
  const world = createWorld(); world.init();
  const Likes = relation();
  const apple = world.spawn();
  const banana = world.spawn();
  const player = world.spawn(Likes(apple), Likes(banana));
  const Removed = createRemoved();
  expect(world.query(Removed(Likes(apple)))).toHaveLength(0);
  player.remove(Likes(apple));
  expect(world.query(Removed(Likes(apple)))).toContain(player);
 });
});
EOF
cp /tmp/debug_incremental.test.ts packages/core/tests/zz-debug.test.ts
cd packages/core && pnpm exec vitest run tests/zz-debug.test.ts 2>&1 | tail -60
cp /tmp/tracking.bak packages/core/src/relation/tracking.ts
rm packages/core/tests/zz-debug.test.ts