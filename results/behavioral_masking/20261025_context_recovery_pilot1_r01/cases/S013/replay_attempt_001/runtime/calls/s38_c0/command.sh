cd /app && cat > /tmp/init_block.py <<'PY'
p='src/container.ts'
s=open(p).read()

marker = """  /**
   * Disposes this container and it's children, calling the disposer
   * on all disposable registrations and clearing the cache.
   */
  function dispose(): Promise<void> {"""

block = r'''
  /**
   * Finds an initialized value for a registration, walking up the parent
   * chain if needed.
   */
  function findInitializedValue(
    name: string | symbol,
  ): CacheEntry | undefined {
    const entry = initializedValues.get(name)
    if (entry !== undefined) {
      return entry
    }
    if (parentContainer) {
      return (parentContainer as any)[FIND_INITIALIZED_VALUE](name)
    }
    return undefined
  }

  /**
   * Checks if a registration has been initialized in this container or any parent.
   */
  function hasInitializedValue(name: string | symbol): boolean {
    if (initializedValues.has(name)) {
      return true
    }
    if (parentContainer) {
      return (parentContainer as any)[HAS_INITIALIZED_VALUE](name)
    }
    return false
  }

  /**
   * A single registration in an initialization plan.
   */
  interface InitializationEntry {
    name: string | symbol
    resolver: Resolver<any>
  }

  /**
   * A level in an initialization plan. All entries in a level are initialized
   * concurrently before the next level begins.
   */
  interface InitializationLevel {
    entries: Array<InitializationEntry>
  }

  /**
   * Extracts dependency names from a resolver. Dependencies are parsed when the
   * resolver is created and exposed on the resolve function.
   */
  function getResolverDependencies(
    resolver: Resolver<any>,
  ): Array<string | symbol> {
    const resolve = (resolver as any).resolve
    const dependencies = resolve && resolve.dependencies
    if (!Array.isArray(dependencies)) {
      return []
    }
    return dependencies.map(
      (dep: { name: string | symbol }) => dep.name,
    )
  }

  /**
   * Builds the initialization plan: registrations with an initializer grouped
   * into dependency levels. Throws AwilixResolutionError if a cycle is detected.
   */
  function buildInitializationPlan(): Array<InitializationLevel> {
    const entries: Array<InitializationEntry> = []
    const localNames = [
      ...Object.keys(registrations),
      ...Object.getOwnPropertySymbols(registrations),
    ]
    for (const name of localNames) {
      const resolver = registrations[name as any] as Resolver<any>
      if (resolver && typeof (resolver as any).initializer === 'function') {
        entries.push({ name, resolver })
      }
    }

    if (entries.length === 0) {
      return []
    }

    const byName = new Map<string | symbol, InitializationEntry>()
    for (const entry of entries) {
      byName.set(entry.name, entry)
    }

    // Map each initialized registration to the initialized registrations it
    // depends on.
    const dependencies = new Map<
      string | symbol,
      Array<string | symbol>
    >()
    for (const entry of entries) {
      const deps = getResolverDependencies(entry.resolver).filter(
        (depName) => byName.has(depName),
      )
      dependencies.set(entry.name, deps)
    }

    // Detect cycles using DFS.
    const visiting = new Set<string | symbol>()
    const visited = new Set<string | symbol>()
    const path: ResolutionStack = []

    const visit = (name: string | symbol) => {
      if (visiting.has(name)) {
        throw new AwilixResolutionError(
          name,
          path,
          'Cyclic dependencies detected.',
        )
      }
      if (visited.has(name)) {
        return
      }
      visiting.add(name)
      path.push({
        name,
        lifetime:
          (byName.get(name)!.resolver.lifetime ||
            Lifetime.TRANSIENT) as LifetimeType,
      })
      for (const depName of dependencies.get(name) || []) {
        visit(depName)
      }
      path.pop()
      visiting.delete(name)
      visited.add(name)
    }

    for (const entry of entries) {
      visit(entry.name)
    }

    // Compute levels: a registration is in the current level once all of its
    // initialized dependencies have been processed.
    const levels: Array<InitializationLevel> = []
    const processed = new Set<string | symbol>()
    const remaining = new Set<string | symbol>(entries.map((e) => e.name))

    while (remaining.size > 0) {
      const levelEntries: Array<InitializationEntry> = []
      for (const name of remaining) {
        const deps = dependencies.get(name) || []
        if (deps.every((depName) => processed.has(depName))) {
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
  }

  /**
   * Initializes the container. Resolves all registrations with an `initializer`
   * in dependency order, running initializers within a level concurrently.
   */
  function initialize(
    options: InitializeOptions = {},
  ): Promise<InitializeResult> {
    if (initializationState.status === 'success') {
      return Promise.resolve(initializationState.result)
    }
    if (initializationState.status === 'failed') {
      return Promise.reject(
        new Error(
          'Cannot re-initialize the container because it previously failed.',
        ),
      )
    }
    if (initializationState.status === 'initializing') {
      return initializationState.promise
    }

    let plan: Array<InitializationLevel>
    try {
      plan = buildInitializationPlan()
    } catch (err) {
      // Graph construction failures (e.g. cyclic dependencies) must not mark
      // the container as failed, allowing initialize() to be retried.
      return Promise.reject(err)
    }

    const promise = runInitialization(plan, options).then(
      (result) => {
        initializationState = { status: 'success', result }
        return result
      },
      (err) => {
        initializationState = { status: 'failed', error: err as Error }
        throw err
      },
    )
    initializationState = { status: 'initializing', promise }
    return promise
  }

  /**
   * Runs a level of initializers, waiting for all in-flight initializers to
   * complete before throwing. If any initializer fails, the first error is
   * rethrown after all tasks have settled.
   */
  async function runLevel<T>(
    entries: Array<T>,
    concurrency: number,
    task: (entry: T) => Promise<void>,
  ): Promise<void> {
    if (entries.length === 0) {
      return
    }
    let index = 0
    const errors: unknown[] = []
    const workerCount = Math.max(1, Math.min(concurrency, entries.length))
    const workers = Array.from({ length: workerCount }, async () => {
      while (index < entries.length) {
        const current = index++
        try {
          await task(entries[current])
        } catch (err) {
          errors.push(err)
        }
      }
    })
    await Promise.all(workers)
    if (errors.length > 0) {
      throw errors[0]
    }
  }

  /**
   * Stores an initialized value in the appropriate lifetime cache.
   */
  function setInitializedCacheValue(
    name: string | symbol,
    resolver: Resolver<any>,
    value: any,
  ): void {
    const lifetime = resolver.lifetime || Lifetime.TRANSIENT
    const targetCache =
      lifetime === Lifetime.SINGLETON ? rootContainer.cache : container.cache
    targetCache.set(name, { resolver, value })
  }

  /**
   * Removes an initialized value from the lifetime caches.
   */
  function clearInitializedCacheValue(name: string | symbol): void {
    container.cache.delete(name)
    if (rootContainer.cache !== container.cache) {
      rootContainer.cache.delete(name)
    }
  }

  /**
   * Rolls back already-initialized services in reverse order. Disposer errors
   * are ignored so they never override the original initialization error.
   */
  async function rollbackInitialized(
    stack: Array<InitializationEntry & { value: any }>,
  ): Promise<void> {
    for (let i = stack.length - 1; i >= 0; i--) {
      const { name, resolver, value } = stack[i]
      const disposable = resolver as DisposableResolver<any>
      if (disposable.dispose) {
        try {
          await disposable.dispose(value)
        } catch {
          // Ignore disposer errors during rollback.
        }
      }
      initializedValues.delete(name)
      clearInitializedCacheValue(name)
    }
  }

  /**
   * Executes the initialization plan and returns metrics.
   */
  async function runInitialization(
    levels: Array<InitializationLevel>,
    options: InitializeOptions,
  ): Promise<InitializeResult> {
    const start = performance.now()
    const metrics: Record<string | symbol, InitializeMetrics> = {}
    const initializedStack: Array<
      InitializationEntry & { value: any }
    > = []

    try {
      for (
        let levelIndex = 0;
        levelIndex < levels.length;
        levelIndex++
      ) {
        const level = levels[levelIndex]
        await runLevel(
          level.entries,
          options.concurrency ?? Infinity,
          async (entry) => {
            const metricStart = performance.now()
            let value: any
            try {
              const instance = entry.resolver.resolve(container)
              const initializer = (entry.resolver as any)
                .initializer as Initializer<any>
              const result = await initializer(instance)
              value = result === undefined ? instance : result
            } catch (err) {
              throw new AwilixInitializationError(
                entry.name,
                err as Error,
              )
            }

            initializedValues.set(entry.name, {
              resolver: entry.resolver,
              value,
            })
            setInitializedCacheValue(entry.name, entry.resolver, value)
            initializedStack.push({ ...entry, value })
            metrics[entry.name] = {
              duration: performance.now() - metricStart,
              level: levelIndex,
            }
          },
        )
      }

      return {
        totalDuration: performance.now() - start,
        metrics,
      }
    } catch (err) {
      await rollbackInitialized(initializedStack)
      throw err
    }
  }

  /**
   * Disposes this container and it's children, calling the disposer
   * on all disposable registrations and clearing the cache.
   */
  function dispose(): Promise<void> {'''

assert marker in s, "marker not found"
s = s.replace(marker, block, 1)

open(p,'w').write(s)
print("block inserted")
PY
python3 /tmp/init_block.py && grep -n "function dispose\|function initialize\|function runInitialization" src/container.ts