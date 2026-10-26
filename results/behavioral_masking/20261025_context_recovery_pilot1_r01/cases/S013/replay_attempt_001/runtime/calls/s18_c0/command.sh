cd /app && python3 - <<'PY'
import re
p='src/resolvers.ts'
s=open(p).read()

# 1. Add Initializer type after Disposer type
s = s.replace(
"""export type Disposer<T> = (value: T) => any | Promise<any>
""",
"""export type Disposer<T> = (value: T) => any | Promise<any>

/**
 * Initializer function type. Called with the resolved instance during
 * `container.initialize()`. May return a replacement instance.
 */
export type Initializer<T> = (instance: T) => T | Promise<T>
""", 1)

# 2. Add initializer to BuildResolver interface method list
s = s.replace(
"""  transient(): this
  proxy(): this
  classic(): this
  inject(injector: InjectorFunction): this
}""",
"""  transient(): this
  proxy(): this
  classic(): this
  inject(injector: InjectorFunction): this
  initializer(initializer: Initializer<T>): this
}""", 1)

# 3. Add initializer to BuildResolverOptions
s = s.replace(
"""  /**
   * Injector function to provide additional parameters.
   */
  injector?: InjectorFunction
}

/**
 * A class constructor. For example:""",
"""  /**
   * Injector function to provide additional parameters.
   */
  injector?: InjectorFunction
  /**
   * Initializer function called with the resolved instance during
   * `container.initialize()`. May return a replacement instance.
   */
  initializer?: Initializer<T>
}

/**
 * A class constructor. For example:""", 1)

# 4. Add initializer method to createBuildResolver updateResolver target
s = s.replace(
"""  return updateResolver(obj, {
    setLifetime,
    inject,
    transient: partial(setLifetime, Lifetime.TRANSIENT),
    scoped: partial(setLifetime, Lifetime.SCOPED),
    singleton: partial(setLifetime, Lifetime.SINGLETON),
    setInjectionMode,
    proxy: partial(setInjectionMode, InjectionMode.PROXY),
    classic: partial(setInjectionMode, InjectionMode.CLASSIC),
  })""",
"""  function setInitializer(this: any, initializer: Initializer<T>) {
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
    initializer: setInitializer,
  })""", 1)

open(p,'w').write(s)
print("patched")
PY
grep -n "Initializer\|initializer" src/resolvers.ts