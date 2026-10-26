cd /app && cat > .tmp-json2.ts <<'EOF'
import { item, string } from './src/index.js'
import { JSONSchemer } from './src/schema/actions/jsonSchemer/index.js'
const sch = item({ pk: string().key(), type: string().enum('a','b'), details: string().optional().requiredIf('type','a').requiredIf('type','b') })
sch.check()
console.log(JSON.stringify(new JSONSchemer(sch).formattedValueSchema(), null, 1))
EOF
npx tsx .tmp-json2.ts && rm -f .tmp-json2.ts