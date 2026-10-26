cd /app && cat > .tmp-json.ts <<'EOF'
import { item, map, string } from './src/index.js'
import { JSONSchemer } from './src/schema/actions/jsonSchemer/index.js'

const sch = item({
  pk: string().key(),
  type: string().enum('a', 'b'),
  details: string().optional().requiredIf('type', 'a').requiredIf('other', 'x'),
  other: string().optional()
})
sch.check()
const js = new JSONSchemer(sch).formattedValueSchema()
console.log(JSON.stringify(js, null, 2))

const sch2 = item({
  pk: string().key(),
  profile: map({ type: string().enum('x','y'), bio: string().optional().requiredIf('type','x') })
})
sch2.check()
console.log('--- nested ---')
console.log(JSON.stringify(new JSONSchemer(sch2).formattedValueSchema(), null, 2))
EOF
cd /app && npx tsx .tmp-json.ts