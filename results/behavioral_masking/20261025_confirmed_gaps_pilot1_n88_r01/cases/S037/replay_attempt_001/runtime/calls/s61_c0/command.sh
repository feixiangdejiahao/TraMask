cd /app && cat > test/jest/debug5.test.js <<'EOF'
import { kea, resetContext, actions, reducers, selectors } from '../../src'

test('debug array first then hasTen', () => {
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
  const h1 = logic.values.hasTen
  console.log('h1', h1, 'hasEvals', hasEvals)
  const h2 = logic.values.hasTen
  console.log('h2', h2, 'hasEvals', hasEvals)
  console.log('health', JSON.stringify(logic.selectorHealth()))
})
EOF
NODE_ENV=development BABEL_ENV=test npx jest test/jest/debug5.test.js 2>&1 | grep -E "first|h1|h2|health"
rm -f test/jest/debug5.test.js