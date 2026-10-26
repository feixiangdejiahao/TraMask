cd /app && python3 - <<'PY'
p='src/core/reducers.ts'
s=open(p).read()
old = """      // create selector for reducer
      if (!logic.selectors[key]) {
        addSelectorAndValue(
          logic,
          key,
          createSelector(logic.selector!, (state) => state[key]),
        )
      }
"""
new = """      // create selector for reducer
      if (!logic.selectors[key]) {
        addSelectorAndValue(
          logic,
          key,
          getContext().options.atomicSelectors
            ? getAtomicEngine(logic as any).createReducerSelector(key)
            : createSelector(logic.selector!, (state) => state[key]),
        )
      }
"""
assert old in s
s=s.replace(old,new)
# add import for getContext and getAtomicEngine
s=s.replace("import { getStoreState } from '../kea/context'", "import { getContext, getStoreState } from '../kea/context'")
s=s.replace("import { addSelectorAndValue } from './selectors'\n", "import { addSelectorAndValue } from './selectors'\nimport { getAtomicEngine } from './atomic-selectors'\n")
open(p,'w').write(s)
print('done')
PY
sed -n '1,15p' src/core/reducers.ts