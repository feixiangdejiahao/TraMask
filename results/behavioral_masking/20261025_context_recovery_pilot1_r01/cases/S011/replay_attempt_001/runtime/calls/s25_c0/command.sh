cat > /tmp/container_patch2.py <<'PYEOF'
p='src/container.ts'
s=open(p).read()

# --- resolve not-initialized check ---
s=s.replace(
"""        throw new AwilixResolutionError(name, resolutionStack)
      }

      const lifetime = resolver.lifetime || Lifetime.TRANSIENT""",
"""        throw new AwilixResolutionError(name, resolutionStack)
      }

      // Registrations with an initializer must be initialized before they can
      // be resolved. During `initialize()` the service is marked as initialized
      // before its initializer runs, so this only blocks uninitialized services.
      if (resolver.initializer && !isInitialized(name)) {
        throw new AwilixNotInitializedError(name)
      }

      const lifetime = resolver.lifetime || Lifetime.TRANSIENT""")

# --- insert implementation before dispose() ---
anchor = """  /**
   * Disposes this container and it's children, calling the disposer
   * on all disposable registrations and clearing the cache.
   */
  function dispose(): Promise<void> {"""

implementation = '''  /**
   * Initializes all registrations in this container that have an initializer,
   * respecting the dependency graph by organizing services into levels.
   *
   * If initialization fails, all successfully initialized services are disposed
   * in reverse order. The container is then marked as failed and cannot be
   * re-initialized.
   */
  function initialize(options: InitializeOptions = {}): Promise<InitializationResult> {
    if (initializationResult) {
      return Promise.resolve(initializationResult)
    }

    if (initializationError) {
      return Promise.reject(
        new AwilixInitializationError(
          `Cannot re-initialize container after a previous initialization failed: ${getErrorMessage(
            initializationError,
          )}`,
          initializationError,
        ),
      )
    }

    // Build the dependency graph synchronously. Graph construction failures
    // (e.g. circular dependencies) must NOT transition the container into a
    // failed state, so initialize() can be retried after fixing the graph.
    let levels: Array<Array<string | symbol>>
    try {
      levels = buildInitializationLevels()
    } catch (err) {
      return Promise.reject(err)
    }

    if (!initializationPromise) {
      initializationPromise = doInitialize(levels, options)
    }

    return initializationPromise
  }

  /**
   * Returns true if the registration with the given name has been initialized,
   * either by this container or by one of its ancestors.
   */
  function isInitialized(name: string | symbol): boolean {
    if (initializedRegistrations.has(name)) {
      return true
    }

    // The resolver may belong to an ancestor (e.g. a parent singleton that was
    // initialized when the parent container was initialized independently).
    for (const ancestor of familyTree.slice(1)) {
      if ((ancestor as any)[HAS_OWN_REGISTRATION]?.(name)) {
        return !!((ancestor as any)[IS_INITIALIZED]?.(name))
      }
    }

    return false
  }

  /**
   * Runs the actual initialization once the dependency levels are known.
   */
  async function doInitialize(
    levels: Array<Array<string | symbol>>,
    options: InitializeOptions,
  ): Promise<InitializationResult> {
    const startTime = performance.now()
    const metrics: Record<string, ServiceMetrics> = {}

    try {
      for (let level = 0; level < levels.length; level++) {
        await initializeLevel(levels[level], level, options.concurrency, metrics)
      }
    } catch (err) {
      // Roll back all already-initialized services in reverse order. Other
      // in-flight initializers in the failing level have already completed
      // because initializeLevel waits for all workers to settle.
      await rollback()
      initializationError = err
      throw err
    }

    const result: InitializationResult = {
      totalDuration: performance.now() - startTime,
      metrics,
    }

    initializationResult = result
    return result
  }

  /**
   * Initializes every service in a level in parallel, honoring the concurrency
   * limit. If a service fails, no new services are started, but in-flight
   * initializers are allowed to complete before the failure is propagated.
   */
  async function initializeLevel(
    level: Array<string | symbol>,
    levelIndex: number,
    concurrency: number | undefined,
    metrics: Record<string, ServiceMetrics>,
  ): Promise<void> {
    const tasks = level.map((name) => ({
      name,
      resolver: registrations[name] as Resolver<any>,
    }))

    const queue = [...tasks]
    const maxWorkers = Math.max(
      1,
      Math.min(concurrency ?? tasks.length, tasks.length),
    )

    let firstError: unknown = null
    let stopped = false

    async function worker() {
      while (!stopped) {
        const task = queue.shift()
        if (!task) {
          break
        }

        try {
          await initializeService(
            task.name,
            task.resolver,
            metrics,
            levelIndex,
          )
        } catch (err) {
          if (firstError === null) {
            firstError = err
          }
          stopped = true
        }
      }
    }

    await Promise.all(
      Array.from({ length: maxWorkers }, () => worker()),
    )

    if (firstError !== null) {
      throw firstError
    }
  }

  /**
   * Resolves and initializes a single service, recording its metrics.
   */
  async function initializeService(
    name: string | symbol,
    resolver: Resolver<any>,
    metrics: Record<string, ServiceMetrics>,
    levelIndex: number,
  ): Promise<void> {
    const startTime = performance.now()

    // Mark as initialized before resolving so the resolve-not-initialized
    // guard does not reject the service currently being initialized.
    initializedRegistrations.add(name)

    let value
    try {
      value = resolve(name)
      if (resolver.initializer) {
        value = await resolver.initializer(value)
      }

      updateCacheEntry(name, resolver, value)
      initializedServices.push({ name, resolver, value })
      metrics[name.toString()] = {
        duration: performance.now() - startTime,
        level: levelIndex,
      }
    } catch (err) {
      initializedRegistrations.delete(name)
      throw new AwilixInitializationError(
        `Failed to initialize '${name.toString()}': ${getErrorMessage(err)}`,
        err,
      )
    }
  }

  /**
   * Updates the cached value after an initializer returns a replacement.
   */
  function updateCacheEntry(
    name: string | symbol,
    resolver: Resolver<any>,
    value: any,
  ): void {
    const lifetime = resolver.lifetime || Lifetime.TRANSIENT
    if (lifetime === Lifetime.SINGLETON) {
      const entry = rootContainer.cache.get(name)
      if (entry) {
        entry.value = value
      }
    } else if (lifetime === Lifetime.SCOPED) {
      const entry = container.cache.get(name)
      if (entry) {
        entry.value = value
      }
    }
  }

  /**
   * Rolls back a failed initialization by disposing all successfully
   * initialized services in reverse order. Disposer errors are swallowed so
   * they never override the original initialization error.
   */
  async function rollback(): Promise<void> {
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
  }

  /**
   * Builds the dependency levels for all registrations that have an
   * initializer. Level 0 contains services with no dependencies on other
   * initializable services; every level N depends only on levels < N.
   *
   * Throws AwilixResolutionError if a cycle is detected.
   */
  function buildInitializationLevels(): Array<Array<string | symbol>> {
    const names = Object.keys(registrations).filter(
      (name) => registrations[name].initializer,
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
    let current = names.filter((name) => (inDegree.get(name) ?? 0) === 0)

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
  }

  /**
   * Finds a cycle path among the given nodes for error reporting.
   */
  function findCyclePath(
    graph: Map<string | symbol, Set<string | symbol>>,
    remaining: Array<string | symbol>,
  ): ResolutionStack {
    const remainingSet = new Set<string | symbol>(remaining)
    const visited = new Set<string | symbol>()
    const path: Array<string | symbol> = []

    function dfs(node: string | symbol): Array<string | symbol> | null {
      const existingIndex = path.indexOf(node)
      if (existingIndex > -1) {
        return path.slice(existingIndex).concat(node)
      }
      if (visited.has(node)) {
        return null
      }

      visited.add(node)
      path.push(node)

      for (const dependency of graph.get(node) ?? []) {
        if (remainingSet.has(dependency)) {
          const cycle = dfs(dependency)
          if (cycle) {
            return cycle
          }
        }
      }

      path.pop()
      return null
    }

    for (const node of remaining) {
      const cycle = dfs(node)
      if (cycle) {
        return cycle.map((name) => ({
          name,
          lifetime: Lifetime.TRANSIENT,
        }))
      }
    }

    return remaining.map((name) => ({
      name,
      lifetime: Lifetime.TRANSIENT,
    }))
  }

  /**
   * Returns the message of an unknown error, falling back to String(err).
   */
  function getErrorMessage(err: unknown): string {
    return err instanceof Error ? err.message : String(err)
  }

'''

s=s.replace(anchor, implementation + anchor)
open(p,'w').write(s)
print('patch2 done')
PYEOF
python3 /tmp/container_patch2.py
grep -n "function initialize\|function isInitialized\|function doInitialize\|function initializeLevel\|function initializeService\|function buildInitializationLevels\|function rollback\|function findCyclePath\|function getErrorMessage" src/container.ts