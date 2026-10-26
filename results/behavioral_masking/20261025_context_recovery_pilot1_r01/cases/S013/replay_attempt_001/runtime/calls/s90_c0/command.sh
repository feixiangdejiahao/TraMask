cd /app && python3 - <<'PY'
p='src/container.ts'
s=open(p).read()

old = """  function buildInitializationPlan(): Array<InitializationLevel> {
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
    }"""

new = """  function buildInitializationPlan(): Array<InitializationLevel> {
    const allRegistrations = rollUpRegistrations()
    const allNames = [
      ...Object.keys(allRegistrations),
      ...Object.getOwnPropertySymbols(allRegistrations),
    ]

    // Parent-owned singletons are owned by the root container and are not
    // re-initialized when a scoped container is initialized.
    const isParentOwnedSingleton = (
      name: string | symbol,
      resolver: Resolver<any>,
    ) =>
      !!parentContainer &&
      (resolver.lifetime || Lifetime.TRANSIENT) === Lifetime.SINGLETON &&
      !Object.prototype.hasOwnProperty.call(registrations, name)

    const entries: Array<InitializationEntry> = []
    for (const name of allNames) {
      const resolver = allRegistrations[name as any] as Resolver<any>
      if (
        resolver &&
        typeof (resolver as any)[INITIALIZER] === 'function' &&
        !isParentOwnedSingleton(name, resolver)
      ) {
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

    // Build a graph over all registrations visible to this container. Edges go
    // from a registration to the registrations it depends on.
    const graph = new Map<string | symbol, Array<string | symbol>>()
    for (const name of allNames) {
      const resolver = allRegistrations[name as any] as Resolver<any>
      graph.set(
        name,
        resolver
          ? getResolverDependencies(resolver).filter((depName) =>
              Object.prototype.hasOwnProperty.call(allRegistrations, depName),
            )
          : [],
      )
    }"""

assert old in s
s=s.replace(old,new)
open(p,'w').write(s)
print("plan updated to rolled-up with singleton skip")
PY
cd /app && npx tsc -p tsconfig.build.json --noEmit --pretty 2>&1 | head -20; echo "tsc: $?"