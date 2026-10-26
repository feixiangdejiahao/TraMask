cd /app && python3 - <<'PYEOF'
p='src/container.ts'
s=open(p).read()

# 1. initialize levels type
s=s.replace(
"""    let levels: Array<Array<string | symbol>>
    try {
      levels = buildInitializationLevels()
    } catch (err) {""",
"""    let levels: Array<Array<InitializationEntry>>
    try {
      levels = buildInitializationLevels()
    } catch (err) {""")

# 2. Replace isInitialized + add helpers
old_isinit = """  /**
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
"""
new_isinit = """  /**
   * Returns the container that owns the registration with the given name.
   */
  function getOwnerContainer(
    name: string | symbol,
  ): AwilixContainer<any> | null {
    if (registrations[name]) {
      return container
    }

    for (const ancestor of familyTree.slice(1)) {
      if ((ancestor as any)[HAS_OWN_REGISTRATION]?.(name)) {
        return ancestor
      }
    }

    return null
  }

  /**
   * Marks or unmarks the given registration as initialized for the container
   * that owns its instance. Singletons are tracked on the owning container
   * (shared across the family tree), while scoped/transient instances are
   * tracked on the current container.
   */
  function markInitialized(
    name: string | symbol,
    resolver: Resolver<any>,
    initialized: boolean,
  ): void {
    const owner =
      resolver.lifetime === Lifetime.SINGLETON
        ? (getOwnerContainer(name) ?? container)
        : container

    ;(owner as any)[SET_INITIALIZED]?.(name, initialized)
    if (initialized) {
      initializedRegistrations.add(name)
    } else {
      initializedRegistrations.delete(name)
    }
  }

  /**
   * Returns true if the registration's instance for this container has been
   * initialized. Singletons are considered initialized if the owning ancestor
   * initialized them; scoped/transient instances are only considered
   * initialized when the current container initialized them.
   */
  function isInitialized(
    name: string | symbol,
    resolver: Resolver<any>,
  ): boolean {
    if (resolver.lifetime === Lifetime.SINGLETON) {
      const owner = getOwnerContainer(name)
      return owner ? !!((owner as any)[IS_INITIALIZED]?.(name)) : false
    }

    return initializedRegistrations.has(name)
  }
"""
assert old_isinit in s
s=s.replace(old_isinit, new_isinit)

# 3. doInitialize types
s=s.replace(
"""  async function doInitialize(
    levels: Array<Array<string | symbol>>,
    options: InitializeOptions,
  ): Promise<InitializationResult> {""",
"""  async function doInitialize(
    levels: Array<Array<InitializationEntry>>,
    options: InitializeOptions,
  ): Promise<InitializationResult> {""")

# 4. initializeLevel accepts entries
s=s.replace(
"""  async function initializeLevel(
    level: Array<string | symbol>,
    levelIndex: number,
    concurrency: number | undefined,
    metrics: Record<string, ServiceMetrics>,
  ): Promise<void> {
    const tasks = level.map((name) => ({
      name,
      resolver: registrations[name] as Resolver<any>,
    }))

    const queue = [...tasks]""",
"""  async function initializeLevel(
    level: Array<InitializationEntry>,
    levelIndex: number,
    concurrency: number | undefined,
    metrics: Record<string, ServiceMetrics>,
  ): Promise<void> {
    const queue = [...level]""")

# 5. initializeService mark/unmark
s=s.replace(
"""    // Mark as initialized before resolving so the resolve-not-initialized
    // guard does not reject the service currently being initialized.
    initializedRegistrations.add(name)

    let value
    try {
      value = resolve(name)""",
"""    // Mark as initialized before resolving so the resolve-not-initialized
    // guard does not reject the service currently being initialized.
    markInitialized(name, resolver, true)

    let value
    try {
      value = resolve(name)""")
s=s.replace(
"""    } catch (err) {
      initializedRegistrations.delete(name)
      throw new AwilixInitializationError(""",
"""    } catch (err) {
      markInitialized(name, resolver, false)
      throw new AwilixInitializationError(""")

# 6. resolve check now passes resolver
s=s.replace(
"""      if (getInitializer(resolver) && !isInitialized(name)) {""",
"""      if (getInitializer(resolver) && !isInitialized(name, resolver)) {""")

open(p,'w').write(s)
print('part 2 done')
PYEOF