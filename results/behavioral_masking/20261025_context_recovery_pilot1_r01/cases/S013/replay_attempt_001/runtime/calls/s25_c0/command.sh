cd /app && python3 - <<'PY'
p='src/container.ts'
s=open(p).read()

# Add initialize to interface after dispose
s=s.replace(
"""  /**
   * Disposes this container and it's children, calling the disposer
   * on all disposable registrations and clearing the cache.
   * Only applies to registrations with `SCOPED` or `SINGLETON` lifetime.
   */
  dispose(): Promise<void>
}""",
"""  /**
   * Disposes this container and it's children, calling the disposer
   * on all disposable registrations and clearing the cache.
   * Only applies to registrations with `SCOPED` or `SINGLETON` lifetime.
   */
  dispose(): Promise<void>
  /**
   * Initializes the container by resolving all registrations with an
   * `initializer`, running the initializers in dependency order.
   *
   * @param {InitializeOptions} options
   * @return {Promise<InitializeResult>}
   */
  initialize(options?: InitializeOptions): Promise<InitializeResult>
}""")

# Add types after CacheEntry
s=s.replace(
"""/**
 * Register a Registration
 * @interface NameAndRegistrationPair
 */""",
"""/**
 * Options for initializing the container.
 */
export interface InitializeOptions {
  /**
   * The maximum number of initializers to run concurrently within a
   * single dependency level. Defaults to `Infinity`.
   */
  concurrency?: number
}

/**
 * The result of initializing the container.
 */
export interface InitializeResult {
  /**
   * The total duration in milliseconds.
   */
  totalDuration: number
  /**
   * The metrics for each initialized registration.
   */
  metrics: Record<string | symbol, InitializeMetrics>
}

/**
 * Metrics for an initialized registration.
 */
export interface InitializeMetrics {
  /**
   * The duration in milliseconds it took to initialize the registration.
   */
  duration: number
  /**
   * The dependency level of the registration. All registrations at a
   * given level complete before the next level begins.
   */
  level: number
}

/**
 * Register a Registration
 * @interface NameAndRegistrationPair
 */""")

open(p,'w').write(s)
print("interface/types patched")
PY
grep -n "initialize\|Initialize" src/container.ts | head -30