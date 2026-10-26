cd /app && python3 - <<'PY'
p='test/jest/atomic-selectors.js'
s=open(p).read()
s=s.replace("import { kea, resetContext, getContext, actions, reducers, selectors, path, useValues } from '../../src'", "import { kea, resetContext, getContext, actions, reducers, selectors, path, useValues, activatePlugin } from '../../src'")
# Fix lifecycle test
old = """    const testPlugin = {
      name: 'atomic-test-plugin',
      events: {
        afterLogic(logic) { order.push(`afterLogic:${logic.pathString}`) },
        beforeMount(logic) { order.push(`beforeMount:${logic.pathString}`) },
        afterMount(logic) { order.push(`afterMount:${logic.pathString}`) },
      },
    }
    getContext().plugins.activated.push(testPlugin)
    getContext().plugins.events.afterLogic.push(testPlugin.events.afterLogic)
    getContext().plugins.events.beforeMount.push(testPlugin.events.beforeMount)
    getContext().plugins.events.afterMount.push(testPlugin.events.afterMount)
"""
new = """    const testPlugin = {
      name: 'atomic-test-plugin',
      events: {
        afterLogic(logic) { order.push(`afterLogic:${logic.pathString}`) },
        beforeMount(logic) { order.push(`beforeMount:${logic.pathString}`) },
        afterMount(logic) { order.push(`afterMount:${logic.pathString}`) },
      },
    }
    activatePlugin(testPlugin)
"""
assert old in s
s=s.replace(old,new)
open(p,'w').write(s)
print('updated')
PY
NODE_ENV=development BABEL_ENV=test npx jest test/jest/atomic-selectors.js 2>&1 | tail -120