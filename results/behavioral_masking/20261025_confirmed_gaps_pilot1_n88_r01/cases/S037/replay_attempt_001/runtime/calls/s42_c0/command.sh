cd /app && python3 - <<'PY'
p='src/kea/build.ts'
s=open(p).read()
# add import
s=s.replace("import { addConnection } from '../core/connect'\n", "import { addConnection } from '../core/connect'\nimport { getAtomicEngine } from '../core/atomic-selectors'\n")

# props change branch: add notifyPropsChanged
old = """    if (prevPropsClone && cachedLogic.events.propsChanged) {
      const newPropsClone = { ...cachedLogic.props }
      batchChanges(() => {
        cachedLogic.events.propsChanged?.(newPropsClone, prevPropsClone)
      })
    }
"""
new = """    if (prevPropsClone) {
      if (getContext().options.atomicSelectors) {
        getAtomicEngine(cachedLogic).notifyPropsChanged()
      }
      if (cachedLogic.events.propsChanged) {
        const newPropsClone = { ...cachedLogic.props }
        batchChanges(() => {
          cachedLogic.events.propsChanged?.(newPropsClone, prevPropsClone)
        })
      }
    }
"""
assert old in s
s=s.replace(old,new)

# after build, define selectorHealth
old = """    runPlugins('afterBuild', logic, wrapper.inputs)
  } catch (e) {
"""
new = """    runPlugins('afterBuild', logic, wrapper.inputs)

    if (getContext().options.atomicSelectors) {
      const engine = getAtomicEngine(logic)
      logic.selectorHealth = () => engine.selectorHealth()
    }
  } catch (e) {
"""
assert old in s
s=s.replace(old,new)
open(p,'w').write(s)
print('build updated')
PY
grep -n "atomic\|selectorHealth\|notifyPropsChanged" src/kea/build.ts