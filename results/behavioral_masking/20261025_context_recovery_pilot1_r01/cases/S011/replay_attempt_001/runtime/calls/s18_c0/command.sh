cat >> /tmp/resolvers_patch.py <<'EOF'
import re
p='src/resolvers.ts'
s=open(p).read()

# 1. Add Initializer type after Disposer type
s=s.replace(
"""/**
 * Disposer function type.
 */
export type Disposer<T> = (value: T) => any | Promise<any>
""",
"""/**
 * Disposer function type.
 */
export type Disposer<T> = (value: T) => any | Promise<any>

/**
 * Initializer function type. Receives the resolved instance and may return
 * a replacement instance.
 */
export type Initializer<T> = (instance: T) => T | Promise<T>
""")

# 2. Add initializer to ResolverOptions (so it flows into all resolver options)
s=s.replace(
"""  /**
   * True if this resolver should be excluded from lifetime leak checking. Used by resolvers that
   * wish to uphold the anti-leakage contract themselves. Defaults to false.
   */
  isLeakSafe?: boolean
}""",
"""  /**
   * True if this resolver should be excluded from lifetime leak checking. Used by resolvers that
   * wish to uphold the anti-leakage contract themselves. Defaults to false.
   */
  isLeakSafe?: boolean
  /**
   * Initializer function that is invoked by `container.initialize()` after
   * the instance has been resolved. May return a replacement instance.
   */
  initializer?: Initializer<T>
}""")

# 3. Add initializer to BuildResolver interface
s=s.replace(
"""  classic(): this
  inject(injector: InjectorFunction): this
}""",
"""  classic(): this
  inject(injector: InjectorFunction): this
  initializer(initializer: Initializer<T>): this
}""")

# 4. Add initializer method in createBuildResolver
s=s.replace(
"""  function inject(this: any, injector: InjectorFunction) {
    return createBuildResolver({
      ...this,
      injector,
    })
  }

  return updateResolver(obj, {
    setLifetime,
    inject,
    transient: partial(setLifetime, Lifetime.TRANSIENT),
    scoped: partial(setLifetime, Lifetime.SCOPED),
    singleton: partial(setLifetime, Lifetime.SINGLETON),
    setInjectionMode,
    proxy: partial(setInjectionMode, InjectionMode.PROXY),
    classic: partial(setInjectionMode, InjectionMode.CLASSIC),
  })""",
"""  function inject(this: any, injector: InjectorFunction) {
    return createBuildResolver({
      ...this,
      injector,
    })
  }

  function initializer(this: any, initializer: Initializer<T>) {
    return createBuildResolver({
      ...this,
      initializer,
    })
  }

  return updateResolver(obj, {
    setLifetime,
    inject,
    transient: partial(setLifetime, Lifetime.TRANSIENT),
    scoped: partial(setLifetime, Lifetime.SCOPED),
    singleton: partial(setLifetime, Lifetime.SINGLETON),
    setInjectionMode,
    proxy: partial(setInjectionMode, InjectionMode.PROXY),
    classic: partial(setInjectionMode, InjectionMode.CLASSIC),
    initializer,
  })""")

# 5. Attach dependencies to resolve function in generateResolve
s=s.replace(
"""  // Use a regular function instead of an arrow function to facilitate binding to the resolver.
  return function resolve<T extends object>(
    this: BuildResolver<any>,
    container: AwilixContainer<T>,
  ) {""",
"""  // Use a regular function instead of an arrow function to facilitate binding to the resolver.
  const resolve = function resolve<T extends object>(
    this: BuildResolver<any>,
    container: AwilixContainer<T>,
  ) {""")

# replace the closing of that function - find the end of generateResolve and attach dependencies
s=s.replace(
"""    return fn()
  }
}

/**
 * Parses the dependencies from the given function.
 * If it's a class that extends another class, and it does
 * not have a defined constructor, attempt to parse it's super constructor.
 */""",
"""    return fn()
  }

  // Expose the parsed dependencies so the container can build an
  // initialization graph without having to resolve the service.
  ;(resolve as any).dependencies = dependencies

  return resolve
}

/**
 * Returns the dependency names for the given resolver. Used when building
 * the initialization graph.
 *
 * @param {Resolver} resolver The resolver to inspect.
 * @return {Array<string | symbol>} The dependency names.
 */
export function getDependencies<T>(
  resolver: Resolver<T>,
): Array<string | symbol> {
  const resolve = (resolver as any).resolve
  const dependencies = resolve && resolve.dependencies
  if (!Array.isArray(dependencies)) {
    return []
  }

  return dependencies.map((dependency: Parameter) => dependency.name)
}

/**
 * Parses the dependencies from the given function.
 * If it's a class that extends another class, and it does
 * not have a defined constructor, attempt to parse it's super constructor.
 */""")

open(p,'w').write(s)
print("done")
EOF
python3 /tmp/resolvers_patch.py
sed -n '60,120p' src/resolvers.ts