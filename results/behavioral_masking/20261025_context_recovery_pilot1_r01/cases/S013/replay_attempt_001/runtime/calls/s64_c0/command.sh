cd /app && python3 - <<'PY'
p='src/container.ts'
s=open(p).read()

start_marker = "  function buildInitializationPlan(): Array<InitializationLevel> {"
end_marker = "    return levels\n  }"

start = s.index(start_marker)
end = s.index(end_marker, start) + len(end_marker)

new_func = r'''  function buildInitializationPlan(): Array<InitializationLevel> {
    const entries: Array<InitializationEntry> = []
    const localNames = [
      ...Object.keys(registrations),
      ...Object.getOwnPropertySymbols(registrations),
    ]
    for (const name of localNames) {
      const resolver = registrations[name as any] as Resolver<any>
      if (resolver && typeof (resolver as any)[INITIALIZER] === 'function') {
        entries.push({ name, resolver })
      }
    }

    if (entries.length === 0) {
      return []
    }

    const byName = new Map<string | symbol, InitializationEntry>()
    const initializedNames = new Set<string | symbol>()
    for (const entry of entries) {
      byName.set(entry.name, entry)
      initializedNames.add(entry.name)
    }

    // Build a graph over all local registrations. Edges go from a registration
    // to the local registrations it depends on.
    const graph = new Map<string | symbol, Array<string | symbol>>()
    for (const name of localNames) {
      const resolver = registrations[name as any] as Resolver<any>
      graph.set(
        name,
        resolver
          ? getResolverDependencies(resolver).filter((depName) =>
              Object.prototype.hasOwnProperty.call(registrations, depName),
            )
          : [],
      )
    }

    // For each initialized registration, compute the set of initialized
    // registrations it depends on (directly or through non-initialized
    // registrations). Cycles are detected while traversing.
    const initializedAncestors = new Map<
      string | symbol,
      Set<string | symbol>
    >()

    const collectAncestors = (
      name: string | symbol,
      visiting: Set<string | symbol>,
    ): Set<string | symbol> => {
      const cached = initializedAncestors.get(name)
      if (cached) {
        return cached
      }
      if (visiting.has(name)) {
        throw new AwilixResolutionError(
          name,
          [],
          'Cyclic dependencies detected.',
        )
      }
      visiting.add(name)
      const result = new Set<string | symbol>()
      for (const depName of graph.get(name) || []) {
        if (visiting.has(depName)) {
          throw new AwilixResolutionError(
            depName,
            [],
            'Cyclic dependencies detected.',
          )
        }
        if (initializedNames.has(depName)) {
          result.add(depName)
        }
        const depAncestors = collectAncestors(depName, visiting)
        for (const ancestor of depAncestors) {
          result.add(ancestor)
        }
      }
      visiting.delete(name)
      initializedAncestors.set(name, result)
      return result
    }

    for (const entry of entries) {
      collectAncestors(entry.name, new Set<string | symbol>())
    }

    // Compute levels: an initialized registration is in the current level once
    // all of its initialized ancestors have been processed.
    const levels: Array<InitializationLevel> = []
    const processed = new Set<string | symbol>()
    const remaining = new Set<string | symbol>(entries.map((e) => e.name))

    while (remaining.size > 0) {
      const levelEntries: Array<InitializationEntry> = []
      for (const name of remaining) {
        const ancestors = initializedAncestors.get(name) || new Set()
        let ready = true
        for (const ancestor of ancestors) {
          if (!processed.has(ancestor)) {
            ready = false
            break
          }
        }
        if (ready) {
          levelEntries.push(byName.get(name)!)
        }
      }
      if (levelEntries.length === 0) {
        // Defensive; cycles are already detected above.
        const first = remaining.values().next().value as string | symbol
        throw new AwilixResolutionError(
          first,
          [],
          'Cyclic dependencies detected.',
        )
      }
      for (const entry of levelEntries) {
        processed.add(entry.name)
        remaining.delete(entry.name)
      }
      levels.push({ entries: levelEntries })
    }

    return levels
  }'''

s = s[:start] + new_func + s[end:]
open(p,'w').write(s)
print("buildInitializationPlan rewritten")
PY
cd /app && npx tsc -p tsconfig.build.json --noEmit --pretty 2>&1 | head -40; echo "tsc exit: $?"