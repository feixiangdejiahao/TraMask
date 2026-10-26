cd /app && python3 - <<'PY'
p='src/container.ts'
s=open(p).read()

# Add symbols after ROLL_UP_REGISTRATIONS
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

# Add initialize and symbol props to container object
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

# Add state after rootContainer
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

open(p,'w').write(s)
print("symbols/state patched")
PY