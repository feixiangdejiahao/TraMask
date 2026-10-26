cd /app && cat > /tmp/test_debug.ts <<'EOF'
import { createWorld, relation, $internal } from '/app/packages/core/src/index.ts';
const world = createWorld();
world.init();
const ChildOf = relation();
const parentA = world.spawn();
const childA = world.spawn(ChildOf(parentA));
console.log('world has child', world.has(childA), 'eid', childA.id());
console.log('ctx entityTraits size', world[$internal].entityTraits.size);
console.log('child traits', world[$internal].entityTraits.get(childA));
console.log('has rel', childA.has(ChildOf(parentA)));
childA.remove(ChildOf(parentA));
console.log('after remove ok');
EOF
pnpm exec tsx /tmp/test_debug.ts