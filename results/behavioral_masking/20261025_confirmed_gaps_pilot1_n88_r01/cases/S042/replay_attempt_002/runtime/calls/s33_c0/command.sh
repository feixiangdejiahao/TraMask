cd /app && cat > /tmp/test_current.ts <<'EOF'
import { createWorld, createAdded, createRemoved, createChanged, relation, Or } from '/app/packages/core/src/index.ts';

const world = createWorld();
world.init();
const ChildOf = relation();
const Removed = createRemoved();
const parentA = world.spawn();
const parentB = world.spawn();
const childA = world.spawn(ChildOf(parentA));
const childB = world.spawn(ChildOf(parentB));
childA.remove(ChildOf(parentA));
childB.remove(ChildOf(parentB));
console.log('removed ChildOf', world.query(Removed(ChildOf)).length);
console.log('removed ChildOf + pairA', world.query(Removed(ChildOf), ChildOf(parentA)).length);
console.log('removed ChildOf + pairB', world.query(Removed(ChildOf), ChildOf(parentB)).length);
EOF
pnpm exec tsx /tmp/test_current.ts