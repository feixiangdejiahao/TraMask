cd /app && cat > test/jest/debug7.test.js <<'EOF'
import { kea, resetContext, actions, reducers, selectors } from '../../src'

test('lazy store with atomic', () => {
  resetContext({ atomicSelectors: true })
  const logic = kea([
    actions({ setName: (name) => ({ name }) }),
    reducers({ user: [{ name: 'a' }, { setName: (state, { name }) => ({ ...state, name }) }] }),
    selectors({ userName: [(s) => [s.user], (user) => user.name] }),
  ])
  logic.mount()
  expect(logic.values.userName).toBe('a')
  logic.actions.setName('b')
  expect(logic.values.userName).toBe('b')
})
EOF
NODE_ENV=development BABEL_ENV=test npx jest test/jest/debug7.test.js 2>&1 | tail -10
rm -f test/jest/debug7.test.js