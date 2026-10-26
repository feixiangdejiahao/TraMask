cd /app && cat > /tmp/check_changed_remove.mts <<'EOF'
import { createWorld, createChanged, trait } from '/app/packages/core/src/index.ts';
const world=createWorld(); world.init();
const Changed=createChanged(); const T=trait({x:0});
const e=world.spawn(T);
e.changed(T);
e.remove(T);
const q=world.query(Changed(T));
console.log('trait changed after remove len', q.length);
EOF
pnpm exec tsx /tmp/check_changed_remove.mts