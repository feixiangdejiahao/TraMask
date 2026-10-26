cd /app && python3 - <<'PYEOF'
p='src/resolvers.ts'
s=open(p).read()

# Revert BuildResolver interface to plain extends
s=s.replace(
"""export interface BuildResolver<T>
  extends Omit<Resolver<T>, 'initializer'>,
    Omit<BuildResolverOptions<T>, 'initializer'> {""",
"""export interface BuildResolver<T> extends Resolver<T>, BuildResolverOptions<T> {""")

# Remove initializer data from ResolverOptions
s=s.replace(
"""  /**
   * Initializer function that is invoked by `container.initialize()` after
   * the instance has been resolved. May return a replacement instance.
   */
  initializer?: Initializer<T>
}
""",
"""}
""", 1)

# Add INITIALIZER symbol after RESOLVER symbol
s=s.replace(
"""export const RESOLVER = Symbol('Awilix Resolver Config')
""",
"""export const RESOLVER = Symbol('Awilix Resolver Config')

/**
 * Symbol used to store the configured initializer on a resolver.
 */
const INITIALIZER = Symbol('Awilix Initializer')
""")

# Update initializer method in createBuildResolver
s=s.replace(
"""  function initializer(this: any, initializer: Initializer<T>) {
    return createBuildResolver({
      ...this,
      initializer,
    })
  }""",
"""  function initializer(this: any, initializer: Initializer<T>) {
    return createBuildResolver({
      ...this,
      [INITIALIZER]: initializer,
    })
  }""")

# Add getInitializer helper near getDependencies
s=s.replace(
"""/**
 * Returns the dependency names for the given resolver. Used when building
 * the initialization graph.
 *
 * @param {Resolver} resolver The resolver to inspect.
 * @return {Array<string | symbol>} The dependency names.
 */""",
"""/**
 * Returns the configured initializer for the given resolver, if any.
 *
 * @param {Resolver} resolver The resolver to inspect.
 * @return {Initializer<T> | undefined} The initializer.
 */
export function getInitializer<T>(
  resolver: Resolver<T>,
): Initializer<T> | undefined {
  return (resolver as any)[INITIALIZER]
}

/**
 * Returns the dependency names for the given resolver. Used when building
 * the initialization graph.
 *
 * @param {Resolver} resolver The resolver to inspect.
 * @return {Array<string | symbol>} The dependency names.
 */""")

open(p,'w').write(s)
print('resolvers updated')

# Update container.ts to use getInitializer
p='src/container.ts'
s=open(p).read()
s=s.replace(
"""  asClass,
  asFunction,
  getDependencies,
} from './resolvers'""",
"""  asClass,
  asFunction,
  getDependencies,
  getInitializer,
} from './resolvers'""")

s=s.replace(
"""      if (resolver.initializer && !isInitialized(name)) {""",
"""      if (getInitializer(resolver) && !isInitialized(name)) {""")

s=s.replace(
"""      value = resolve(name)
      if (resolver.initializer) {
        value = await resolver.initializer(value)
      }""",
"""      value = resolve(name)
      const initializer = getInitializer(resolver)
      if (initializer) {
        value = await initializer(value)
      }""")

s=s.replace(
"""    const names = Object.keys(registrations).filter(
      (name) => registrations[name].initializer,
    )""",
"""    const names = Object.keys(registrations).filter(
      (name) => getInitializer(registrations[name]),
    )""")

open(p,'w').write(s)
print('container updated')
PYEOF
# remove debug logging from container
python3 - <<'PYEOF'
p='src/container.ts'
s=open(p).read()
s=s.replace("""            if (resolved === resolver) {
              console.log('DEBUG resolve returned resolver for', name)
            }
""", "")
s=s.replace("""      value = resolve(name)
      console.log('DEBUG initializeService', name.toString(), 'resolved ctor:', value?.constructor?.name)
      if (resolver.initializer) {
        value = await resolver.initializer(value)
        console.log('DEBUG initializeService after initializer ctor:', value?.constructor?.name)
      }""",
"""      value = resolve(name)
      const initializer = getInitializer(resolver)
      if (initializer) {
        value = await initializer(value)
      }""")
open(p,'w').write(s)
print('debug removed')
PYEOF
npx tsc -p tsconfig.json --noEmit --pretty false 2>&1 | grep -v "examples/typescript" | head -30