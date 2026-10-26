cd /app && cat > test/jest/debug6.test.js <<'EOF'
import { kea, resetContext } from '../../src'

test('empty health', () => {
  resetContext({ atomicSelectors: true, createStore: true })
  const logic = kea([])
  logic.mount()
  console.log('health', JSON.stringify(logic.selectorHealth()))
  console.log('wrapper health', JSON.stringify(logic().selectorHealth()))
})
EOF
NODE_ENV=development BABEL_ENV=test npx jest test/jest/debug6.test.js 2>&1 | grep -E "health|PASS|FAIL"
rm -f test/jest/debug6.test.js