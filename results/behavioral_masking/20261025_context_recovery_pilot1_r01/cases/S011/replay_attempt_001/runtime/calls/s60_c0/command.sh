cd /app && python3 - <<'PYEOF'
p='src/container.ts'
s=open(p).read()

# Replace rollback
old_rollback = """  async function rollback(): Promise<void> {
    const services = initializedServices.slice().reverse()
    for (const { name, resolver, value } of services) {
      const disposable = resolver as DisposableResolver<any>
      if (disposable.dispose) {
        try {
          await disposable.dispose(value)
        } catch {
          // Swallow disposer errors during rollback.
        }
      }
      rootContainer.cache.delete(name)
      container.cache.delete(name)
    }

    initializedServices.length = 0
    initializedRegistrations.clear()
  }"""
new_rollback = """  async function rollback(): Promise<void> {
    const services = initializedServices.slice().reverse()
    for (const { name, resolver, value } of services) {
      const disposable = resolver as DisposableResolver<any>
      if (disposable.dispose) {
        try {
          await disposable.dispose(value)
        } catch {
          // Swallow disposer errors during rollback.
        }
      }
      markInitialized(name, resolver, false)
      rootContainer.cache.delete(name)
      container.cache.delete(name)
    }

    initializedServices.length = 0
  }"""
assert old_rollback in s
s=s.replace(old_rollback, new_rollback)

# Replace buildInitializationLevels
old_build = """  function buildInitializationLevels(): Array<Array<string | symbol>> {
    const names = Object.keys(registrations).filter(
      (name) => getInitializer(registrations[name]),
    )

    if (names.length === 0) {
      return []
    }

    const nameSet = new Set<string | symbol>(names)
    const graph = new Map<string | symbol, Set<string | symbol>>()

    for (const name of names) {
      const resolver = registrations[name]
      const edges = getDependencies(resolver).filter((dependency) =>
        nameSet.has(dependency),
      )
      graph.set(name, new Set(edges))
    }

    const inDegree = new Map<string | symbol, number>()
    for (const [name, deps] of graph) {
      inDegree.set(name, deps.size)
    }

    const levels: Array<Array<string | symbol>> = []
    let current: Array<string | symbol> = names.filter(
      (name) => (inDegree.get(name) ?? 0) === 0,
    )

    while (current.length > 0) {
      levels.push(current)
      const next: Array<string | symbol> = []

      for (const name of current) {
        for (const [dependent, deps] of graph) {
          if (deps.has(name)) {
            const degree = (inDegree.get(dependent) ?? 0) - 1
            inDegree.set(dependent, degree)
            if (degree === 0) {
              next.push(dependent)
            }
          }
        }
      }

      current = next
    }

    const remaining = names.filter((name) => (inDegree.get(name) ?? 0) > 0)
    if (remaining.length > 0) {
      throw new AwilixResolutionError(
        remaining[0],
        findCyclePath(graph, remaining),
        'Cyclic dependencies detected during initialization.',
      )
    }

    return levels
  }"""
new_build = """  function buildInitializationLevels(): Array<Array<InitializationEntry>> {
    const rolledUp = rollUpRegistrations()
    const entries: Array<InitializationEntry> = Object.keys(rolledUp)
      .filter((name) => getInitializer(rolledUp[name]))
      .map((name) => ({
        name,
        resolver: rolledUp[name] as Resolver<any>,
      }))
      .filter(({ name, resolver }) => !isInitialized(name, resolver))

    if (entries.length === 0) {
      return []
    }

    const nameSet = new Set<string | symbol>(entries.map((entry) => entry.name))
    const graph = new Map<
      string | symbol,
      { resolver: Resolver<any>; deps: Set<string | symbol> }
    >()

    for (const { name, resolver } of entries) {
      const edges = getDependencies(resolver).filter((dependency) =>
        nameSet.has(dependency),
      )
      graph.set(name, { resolver, deps: new Set(edges) })
    }

    const inDegree = new Map<string | symbol, number>()
    for (const [name, node] of graph) {
      inDegree.set(name, node.deps.size)
    }

    const levels: Array<Array<InitializationEntry>> = []
    let current: Array<string | symbol> = entries
      .map((entry) => entry.name)
      .filter((name) => (inDegree.get(name) ?? 0) === 0)

    while (current.length > 0) {
      levels.push(
        current.map((name) => ({
          name,
          resolver: graph.get(name)!.resolver,
        })),
      )
      const next: Array<string | symbol> = []

      for (const name of current) {
        for (const [dependent, node] of graph) {
          if (node.deps.has(name)) {
            const degree = (inDegree.get(dependent) ?? 0) - 1
            inDegree.set(dependent, degree)
            if (degree === 0) {
              next.push(dependent)
            }
          }
        }
      }

      current = next
    }

    const remaining = entries
      .map((entry) => entry.name)
      .filter((name) => (inDegree.get(name) ?? 0) > 0)
    if (remaining.length > 0) {
      throw new AwilixResolutionError(
        remaining[0],
        findCyclePath(
          new Map(
            Array.from(graph.entries()).map(([name, node]) => [
              name,
              node.deps,
            ]),
          ),
          remaining,
        ),
        'Cyclic dependencies detected during initialization.',
      )
    }

    return levels
  }"""
assert old_build in s
s=s.replace(old_build, new_build)

open(p,'w').write(s)
print('part 3 done')
PYEOF
npx tsc -p tsconfig.json --noEmit --pretty false 2>&1 | grep -v "examples/typescript" | head -30