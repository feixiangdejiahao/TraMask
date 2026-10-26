cd /app && cat > test/jest/debug4.test.js <<'EOF'
import { kea, resetContext, actions, reducers, selectors } from '../../src'

test('debug array exact2', () => {
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
  const h1 = logic.values.hasTen
  console.log('h1', h1, 'hasEvals', hasEvals)
  const h2 = logic.values.hasTen
  console.log('h2', h2, 'hasEvals', hasEvals)
  console.log('health', JSON.stringify(logic.selectorHealth()))
  console.log('versions list0/1/2', logic.selectorHealth().selectors.hasTen.dependencies)
})
EOF
NODE_ENV=development BABEL_ENV=test npx jest test/jest/debug4.test.js 2>&1 | grep -E "h1|h2|health|versions"
rm -f test/jest/debug4.test.js