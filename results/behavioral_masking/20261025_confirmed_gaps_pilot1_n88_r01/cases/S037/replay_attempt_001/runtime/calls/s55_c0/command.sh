cd /app && cat > test/jest/debug2.test.js <<'EOF'
import { kea, resetContext, actions, reducers, selectors } from '../../src'

test('debug array', () => {
  resetContext({ atomicSelectors: true, createStore: true })
  let firstEvals = 0
  let hasEvals = 0
  const logic = kea([
    actions({ setIndex: (index, value) => ({ index, value }) }),
    reducers({
      list: [[10, 20, 30], { setIndex: (state, { index, value }) => state.map((v, i) => (i === index ? value : v)) }],
    }),
    selectors({
      first: [(s) => [s.list], (list) => { firstEvals += 1; return list[0] }],
      hasTen: [(s) => [s.list], (list) => { hasEvals += 1; return list.includes(10) }],
    }),
  ])
  logic.mount()
  console.log('first', logic.values.first, 'fe', firstEvals)
  console.log('health after first', JSON.stringify(logic.selectorHealth(), null, 2))
  console.log('hasTen', logic.values.hasTen, 'he', hasEvals)
  console.log('health after hasTen', JSON.stringify(logic.selectorHealth(), null, 2))
})
EOF
NODE_ENV=development BABEL_ENV=test npx jest test/jest/debug2.test.js 2>&1 | grep -A5 "health\|first\|hasTen"
rm -f test/jest/debug2.test.js