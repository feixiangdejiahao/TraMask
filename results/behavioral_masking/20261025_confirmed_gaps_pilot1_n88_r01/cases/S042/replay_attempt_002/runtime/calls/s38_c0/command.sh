cd /app && cat > /tmp/test_debug3.ts <<'EOF'
import { createWorld, relation, $internal } from '/app/packages/core/src/index.ts';
const world = createWorld();
world.init();
const ChildOf = relation();
world.reset();
const parentA = world.spawn();
const childA = world.spawn(ChildOf(parentA));
console.log('childA', childA, 'id', childA.id(), 'has map key', world[$internal].entityTraits.has(childA));
for (const [k,v] of world[$internal].entityTraits) console.log('key', k, 'id', (k as any).id?.());
childA.remove(ChildOf(parentA));
console.log('after remove ok');
EOF
pnpm exec tsx /tmp/test_debug3.ts