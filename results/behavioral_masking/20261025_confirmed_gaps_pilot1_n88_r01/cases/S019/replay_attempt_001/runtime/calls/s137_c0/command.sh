cd /app && cat > .tmp-edge3.ts <<'EOF'
import { item, map, string, $set } from './src/index.js'
import { getRequiredIfConditions } from './src/entity/actions/update/updateItemParams/requiredIfConditions.js'

const sch = item({ pk: string().key(), profile: map({ type: string().enum('x','y'), bio: string().optional().requiredIf('type','x') }) })
sch.check()
const cond = getRequiredIfConditions(sch, { pk: 'x', profile: { [$set]: { type: 'x' } } })
console.log('cond:', JSON.stringify(cond))

const cond2 = getRequiredIfConditions(sch, { pk: 'x', profile: { type: 'x' } })
console.log('cond2:', JSON.stringify(cond2))
EOF
cd /app && npx tsx .tmp-edge3.ts