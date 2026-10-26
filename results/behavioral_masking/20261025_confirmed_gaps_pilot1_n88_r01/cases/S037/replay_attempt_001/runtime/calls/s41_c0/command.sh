cd /app && python3 - <<'PY'
p='src/kea/store.ts'
s=open(p).read()
s=s.replace("import { isPaused } from '../react/hooks'\n", "import { isPaused } from '../react/hooks'\nimport { notifyAtomicEngines } from '../core/atomic-selectors'\n")
old = """  // run pre-hooks
  runPlugins('beforeReduxStore', options)

  // combine middleware into the first enhancer
"""
new = """  // run pre-hooks
  runPlugins('beforeReduxStore', options)

  // The atomic selector engine needs to see state changes before React subscribers run.
  if (context.options.atomicSelectors) {
    options.middleware.push((store) => (next) => (action) => {
      const previousState = store.getState()
      const response = next(action)
      notifyAtomicEngines(previousState, store.getState())
      return response
    })
  }

  // combine middleware into the first enhancer
"""
assert old in s
s=s.replace(old,new)
open(p,'w').write(s)
print('store updated')
PY
sed -n '30,55p' src/kea/store.ts