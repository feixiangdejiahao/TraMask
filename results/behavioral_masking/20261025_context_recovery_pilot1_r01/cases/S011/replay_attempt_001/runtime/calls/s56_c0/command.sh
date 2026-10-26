cd /app && python3 - <<'PYEOF'
p='src/container.ts'
s=open(p).read()

# Add InitializationEntry type after InitializationResult
s=s.replace(
"""/**
 * Register a Registration
 * @interface NameAndRegistrationPair
 */""",
"""/**
 * An entry in an initialization level.
 */
export interface InitializationEntry {
  name: string | symbol
  resolver: Resolver<any>
}

/**
 * Register a Registration
 * @interface NameAndRegistrationPair
 */""")

# Add SET_INITIALIZED symbol
s=s.replace(
"""/**
 * Symbol used to check whether a container has initialized a registration.
 */
const IS_INITIALIZED = Symbol('isInitialized')
""",
"""/**
 * Symbol used to check whether a container has initialized a registration.
 */
const IS_INITIALIZED = Symbol('isInitialized')

/**
 * Symbol used to set whether a container has initialized a registration.
 */
const SET_INITIALIZED = Symbol('setInitialized')
""")

# Add SET_INITIALIZED method to container object
s=s.replace(
"""    [HAS_OWN_REGISTRATION]: (name: string | symbol) => !!registrations[name],
    [IS_INITIALIZED]: (name: string | symbol) =>
      initializedRegistrations.has(name),""",
"""    [HAS_OWN_REGISTRATION]: (name: string | symbol) => !!registrations[name],
    [IS_INITIALIZED]: (name: string | symbol) =>
      initializedRegistrations.has(name),
    [SET_INITIALIZED]: (name: string | symbol, value: boolean) => {
      if (value) {
        initializedRegistrations.add(name)
      } else {
        initializedRegistrations.delete(name)
      }
    },""")

open(p,'w').write(s)
print('part 1 done')
PYEOF