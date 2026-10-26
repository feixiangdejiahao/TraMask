cd /app && cat > .tmp-edge4.ts <<'EOF'
import { $set, $SET } from './src/index.js'
import { isSetting, $SET as S2 } from './src/entity/actions/update/symbols/index.js'
const v = { [$set]: { type: 'x' } }
console.log('same symbol:', $SET === S2)
console.log('v:', v)
console.log('isSetting:', isSetting(v))
console.log('$SET in v:', $SET in v)
console.log('v[$SET]:', JSON.stringify(v[$SET]))
EOF
cd /app && npx tsx .tmp-edge4.ts