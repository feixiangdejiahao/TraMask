cd /app && cat > /tmp/test_debug2.ts <<'EOF'
import { createWorld, relation, $internal } from '/app/packages/core/src/index.ts';
const world = createWorld();
world.init();
const ChildOf = relation();
world.reset();
const parentA = world.spawn();
const childA = world.spawn(ChildOf(parentA));
console.log('map size', world[$internal].entityTraits.size, 'child traits', world[$internal].entityTraits.get(childA));
childA.remove(ChildOf(parentA));
console.log('after remove ok');
EOF
pnpm exec tsx /tmp/test_debug2.ts