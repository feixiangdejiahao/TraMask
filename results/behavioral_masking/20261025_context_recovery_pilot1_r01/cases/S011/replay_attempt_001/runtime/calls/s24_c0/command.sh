cat > /tmp/container_patch1.py <<'PYEOF'
p='src/container.ts'
s=open(p).read()

# --- imports ---
s=s.replace(
"""import * as util from 'util'
import {
  AwilixRegistrationError,
  AwilixResolutionError,
  AwilixTypeError,
} from './errors'""",
"""import * as util from 'util'
import { performance } from 'perf_hooks'
import {
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
  Resolver,
  asClass,
  asFunction,
  getDependencies,
} from './resolvers'""")

# --- interface: add initialize before dispose ---
s=s.replace(
"""  /**
   * Disposes this container and it's children, calling the disposer
   * on all disposable registrations and clearing the cache.
   * Only applies to registrations with `SCOPED` or `SINGLETON` lifetime.
   */
  dispose(): Promise<void>
}""",
"""  /**
   * Initializes all registrations that have an initializer configured,
   * respecting the dependency graph by organizing them into levels.
   *
   * @param {InitializeOptions} options
   * Options for initialization.
   *
   * @return {Promise<InitializationResult>}
   * A result containing timing metrics for each initialized service.
   */
  initialize(options?: InitializeOptions): Promise<InitializationResult>
  /**
   * Disposes this container and it's children, calling the disposer
   * on all disposable registrations and clearing the cache.
   * Only applies to registrations with `SCOPED` or `SINGLETON` lifetime.
   */
  dispose(): Promise<void>
}""")

# --- add option/result interfaces after CacheEntry ---
s=s.replace(
"""/**
 * Register a Registration
 * @interface NameAndRegistrationPair
 */""",
"""/**
 * Options for `container.initialize()`.
 */
export interface InitializeOptions {
  /**
   * The maximum number of initializers that may run in parallel within a level.
   * Defaults to running all initializers in a level in parallel.
   */
  concurrency?: number
}

/**
 * Timing metrics for a single initialized service.
 */
export interface ServiceMetrics {
  /**
   * How long initialization of the service took, in milliseconds.
   */
  duration: number
  /**
   * The zero-based dependency level the service was initialized in.
   */
  level: number
}

/**
 * The result returned by `container.initialize()`.
 */
export interface InitializationResult {
  /**
   * Total time taken to initialize all services, in milliseconds.
   */
  totalDuration: number
  /**
   * Metrics keyed by registration name.
   */
  metrics: Record<string, ServiceMetrics>
}

/**
 * Register a Registration
 * @interface NameAndRegistrationPair
 */""")

# --- add symbols ---
s=s.replace(
"""const CRADLE_STRING_TAG = 'AwilixContainerCradle'
""",
"""const CRADLE_STRING_TAG = 'AwilixContainerCradle'

/**
 * Symbol used to check whether a container owns a registration.
 */
const HAS_OWN_REGISTRATION = Symbol('hasOwnRegistration')

/**
 * Symbol used to check whether a container has initialized a registration.
 */
const IS_INITIALIZED = Symbol('isInitialized')
""")

# --- state variables ---
s=s.replace(
"""  const resolutionStack: ResolutionStack = parentResolutionStack ?? []

  // Internal registration store for this container.
  const registrations: RegistrationHash = {}""",
"""  const resolutionStack: ResolutionStack = parentResolutionStack ?? []

  /**
   * Tracks the names of registrations in this container that have been
   * successfully initialized (or are currently being initialized).
   */
  const initializedRegistrations: Set<string | symbol> = new Set()

  /**
   * Tracks initialized services in completion order so they can be rolled
   * back (disposed in reverse order) if initialization fails.
   */
  const initializedServices: Array<{
    name: string | symbol
    resolver: Resolver<any>
    value: any
  }> = []

  /**
   * Caches the in-flight/settled `initialize()` promise so that calling
   * `initialize()` multiple times is idempotent.
   */
  let initializationPromise: Promise<InitializationResult> | null = null

  /**
   * The result of a successful initialization.
   */
  let initializationResult: InitializationResult | null = null

  /**
   * The error that caused a previous initialization to fail.
   */
  let initializationError: unknown = null

  // Internal registration store for this container.
  const registrations: RegistrationHash = {}""")

# --- add initialize + symbol methods to container object ---
s=s.replace(
"""    resolve,
    hasRegistration,
    dispose,
    getRegistration,
    [util.inspect.custom]: inspect,
    [ROLL_UP_REGISTRATIONS!]: rollUpRegistrations,""",
"""    resolve,
    hasRegistration,
    initialize,
    dispose,
    getRegistration,
    [util.inspect.custom]: inspect,
    [ROLL_UP_REGISTRATIONS!]: rollUpRegistrations,
    [HAS_OWN_REGISTRATION]: (name: string | symbol) => !!registrations[name],
    [IS_INITIALIZED]: (name: string | symbol) =>
      initializedRegistrations.has(name),""")

open(p,'w').write(s)
print('patch1 done')
PYEOF
python3 /tmp/container_patch1.py
sed -n '1,12p' src/container.ts