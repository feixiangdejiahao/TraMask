cd /app && cat > /tmp/debug.test.js <<'EOF'
import { kea, resetContext, actions, reducers, selectors, getContext } from '../src'

test('debug', () => {
  resetContext({ atomicSelectors: true, createStore: true })
  const logic = kea([
    actions({ setAge: (age) => ({ age }) }),
    reducers({
      user: [{ name: 'a', age: 1 }, { setAge: (state, { age }) => ({ ...state, age }) }],
    }),
    selectors({
      userName: [(s) => [s.user], (user) => user.name],
    }),
  ])
  const built = logic()
  built.mount()
  console.log('state', getContext().store.getState())
  console.log('path', built.path, built.pathString)
  console.log('root', built.selector(getContext().store.getState()))
  try {
    console.log('userName', built.values.userName)
  } catch (e) {
    console.error('ERR', e.message, e.stack)
  }
})
EOF
cp /tmp/debug.test.js test/jest/debug.test.js
BABEL_ENV=test npx jest test/jest/debug.test.js 2>&1 | tail -50
rm -f test/jest/debug.test.js