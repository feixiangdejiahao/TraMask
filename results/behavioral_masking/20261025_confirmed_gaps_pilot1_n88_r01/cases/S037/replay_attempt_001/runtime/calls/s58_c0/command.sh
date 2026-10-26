cd /app && cat > test/jest/debug3.test.js <<'EOF'
import { kea, resetContext, actions, reducers, selectors } from '../../src'

test('debug array exact', () => {
  resetContext({ atomicSelectors: true, createStore: true })
  let firstEvals = 0
  let hasEvals = 0
  const logic = kea([
    actions({ setIndex: (index, value) => ({ index, value }) }),
    reducers({
      list: [
        [10, 20, 30],
        {
          setIndex: (state, { index, value }) => state.map((v, i) => (i === index ? value : v)),
        },
      ],
    }),
    selectors({
      first: [(s) => [s.list], (list) => { firstEvals += 1; return list[0] }],
      hasTen: [(s) => [s.list], (list) => { hasEvals += 1; return list.includes(10) }],
    }),
  ])
  logic.mount()
  console.log('access first =>', logic.values.first)
  console.log('firstEvals', firstEvals, 'hasEvals before hasTen', hasEvals)
  console.log('access hasTen =>', logic.values.hasTen)
  console.log('firstEvals', firstEvals, 'hasEvals', hasEvals)
  console.log('health', JSON.stringify(logic.selectorHealth()))
})
EOF
NODE_ENV=development BABEL_ENV=test npx jest test/jest/debug3.test.js 2>&1 | grep -E "access|Evals|health"
rm -f test/jest/debug3.test.js