cd /app && cat > .tmp-typecheck.ts <<'EOF'
import type { A } from 'ts-toolbelt'
import { string } from './src/index.js'

const attr = string().optional().requiredIf('type', 'a')
const assert1: A.Equals<typeof attr.props.requiredIf, { type: ['a'] }> = 1
assert1

const attr2 = string().optional().requiredIf('type', 'a').requiredIf('type', 'b')
const assert2: A.Equals<typeof attr2.props.requiredIf, { type: ['a', 'b'] }> = 1
assert2

const attr3 = string().optional().requiredIf('type', 'a').requiredIf('other', 1)
const assert3: A.Equals<typeof attr3.props.requiredIf, { type: ['a']; other: [1] }> = 1
assert3
EOF
cd /app && npx tsc --noEmit 2>&1 | head -30; rm -f .tmp-typecheck.ts