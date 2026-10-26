cd /app && python3 - <<'PY'
p='src/core/selectors.ts'
s=open(p).read()
marker = "export function addSelectorAndValue"
addition = '''
function atomicSelectorsBuilder<L extends Logic = Logic>(
  logic: L,
  selectorInputs: SelectorDefinitions<L>,
): void {
  const engine = getAtomicEngine(logic as any)

  const propSelectors =
    typeof Proxy !== 'undefined'
      ? new Proxy(logic.props, {
          get(target, prop) {
            if (!(prop in target)) {
              throw new Error(
                `[KEA] Prop "${String(prop)}" not found for logic "${
                  logic.pathString
                }". Attempted to use in a selector. Please specify a default via props({ ${String(
                  prop,
                )}: '' }) to resolve.`,
              )
            }
            return () => target[prop]
          },
        })
      : (Object.fromEntries(
          Object.keys(logic.props).map((key) => [key, () => logic.props[key]]),
        ) as LogicPropSelectors<L>)

  const entries: { name: string; args: Selector[]; func: (...args: any[]) => any }[] = []
  const staticDependencies = new Map<string, Set<string>>()
  let currentName: string | null = null

  const selectorsProxy = new Proxy(logic.selectors, {
    get(_target, prop, receiver) {
      if (typeof prop === 'symbol') {
        return Reflect.get(_target, prop, receiver)
      }
      const name = String(prop)
      if (currentName) {
        if (!staticDependencies.has(currentName)) {
          staticDependencies.set(currentName, new Set())
        }
        staticDependencies.get(currentName)!.add(name)
      }
      return engine.callSelectorFunction(name)
    },
  })

  for (const entry of Object.entries(selectorInputs)) {
    const [key, arr]: [string, SelectorDefinition<L['selectors'], LogicPropSelectors<L>, any> | undefined] = entry
    if (typeof logic.selectors[key] !== 'undefined') {
      throw new Error(`[KEA] Logic "${logic.pathString}" selector "${key}" already exists`)
    }
    if (!arr) {
      throw new Error(`[KEA] Logic "${logic.pathString}" selector "${key}" is undefined`)
    }
    const [input, func] = arr
    currentName = key
    const args: Selector[] = input(selectorsProxy as any, propSelectors)
    currentName = null

    if (args.filter((a) => typeof a !== 'function').length > 0) {
      const argTypes = args.map((a) => typeof a).join(', ')
      throw new Error(`[KEA] Logic "${logic.pathString}", selector "${key}" has incorrect input: [${argTypes}].`)
    }
    entries.push({ name: key, args, func })
  }

  detectCircularSelectorDependencies(staticDependencies)

  for (const { name, args, func } of entries) {
    addSelectorAndValue(logic, name, engine.createSelector(name, args, func))
  }
}

'''
assert marker in s
s=s.replace(marker, addition + marker)
open(p,'w').write(s)
print('atomic builder inserted')
PY