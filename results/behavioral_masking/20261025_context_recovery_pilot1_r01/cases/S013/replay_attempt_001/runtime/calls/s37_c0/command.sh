cd /app && python3 - <<'PY'
p='src/container.ts'
s=open(p).read()

# 1. Imports
s=s.replace(
"""import {
  AwilixRegistrationError,
  AwilixResolutionError,
  AwilixTypeError,
} from './errors'""",
"""import {
  AwilixInitializationError,
  AwilixNotInitializedError,
  AwilixRegistrationError,
  AwilixResolutionError,
  AwilixTypeError,
} from './errors'""")

s=s.replace(
"""import {
  BuildResolverOptions,
  Constructor,
  DisposableResolver,
  Resolver,
  asClass,
  asFunction,
} from './resolvers'""",
"""import {
  BuildResolverOptions,
  Constructor,
  DisposableResolver,
  Initializer,
  Resolver,
  asClass,
  asFunction,
} from './resolvers'""")

# 2. Interface: add initialize after dispose()
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

# 3. Types after CacheEntry
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

# 4. Symbols
s=s.replace(
"""/**
 * Roll Up Registrations symbol.
 */
const ROLL_UP_REGISTRATIONS = Symbol('rollUpRegistrations')
""",
"""/**
 * Roll Up Registrations symbol.
 */
const ROLL_UP_REGISTRATIONS = Symbol('rollUpRegistrations')

/**
 * Initialized values symbol. Maps registration names to their initialized values.
 */
const INITIALIZED_VALUES = Symbol('initializedValues')

/**
 * Finds an initialized value in this container or any parent.
 */
const FIND_INITIALIZED_VALUE = Symbol('findInitializedValue')

/**
 * Checks if a registration has been initialized in this container or any parent.
 */
const HAS_INITIALIZED_VALUE = Symbol('hasInitializedValue')
""")

# 5. Container object: add initialize and symbol props
s=s.replace(
"""    hasRegistration,
    dispose,
    getRegistration,
    [util.inspect.custom]: inspect,
    [ROLL_UP_REGISTRATIONS!]: rollUpRegistrations,
    get registrations() {
      return rollUpRegistrations()
    },
  }""",
"""    hasRegistration,
    dispose,
    initialize,
    getRegistration,
    [util.inspect.custom]: inspect,
    [ROLL_UP_REGISTRATIONS!]: rollUpRegistrations,
    [INITIALIZED_VALUES]: initializedValues,
    [FIND_INITIALIZED_VALUE]: findInitializedValue,
    [HAS_INITIALIZED_VALUE]: hasInitializedValue,
    get registrations() {
      return rollUpRegistrations()
    },
  }""")

# 6. State after rootContainer
s=s.replace(
"""  // We need a reference to the root container,
  // so we can retrieve and store singletons.
  const rootContainer = last(familyTree)

  return container
""",
"""  // We need a reference to the root container,
  // so we can retrieve and store singletons.
  const rootContainer = last(familyTree)

  /**
   * Values that have been initialized for this container. Keyed by registration name.
   */
  const initializedValues = new Map<string | symbol, CacheEntry>()

  type InitializationState =
    | { status: 'idle' }
    | { status: 'initializing'; promise: Promise<InitializeResult> }
    | { status: 'success'; result: InitializeResult }
    | { status: 'failed'; error: Error }

  /**
   * The initialization state of this container.
   */
  let initializationState: InitializationState = { status: 'idle' }

  return container
""")

# 7. resolve: initialized check
s=s.replace(
"""        throw new AwilixResolutionError(name, resolutionStack)
      }

      const lifetime = resolver.lifetime || Lifetime.TRANSIENT
""",
"""        throw new AwilixResolutionError(name, resolutionStack)
      }

      // If this registration has an initializer, it must be initialized before it can be
      // resolved. If it has already been initialized, return the initialized value.
      if (typeof (resolver as any).initializer === 'function') {
        const initializedEntry = findInitializedValue(name)
        if (initializedEntry !== undefined) {
          return initializedEntry.value
        }
        throw new AwilixNotInitializedError(name)
      }

      const lifetime = resolver.lifetime || Lifetime.TRANSIENT
""")

open(p,'w').write(s)
print("base patches applied")
PY
grep -n "function dispose" src/container.ts