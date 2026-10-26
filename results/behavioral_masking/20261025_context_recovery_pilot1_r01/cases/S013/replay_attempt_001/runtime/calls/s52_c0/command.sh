cd /app && python3 - <<'PY'
p='src/resolvers.ts'
s=open(p).read()

# 1. Add INITIALIZER symbol after RESOLVER symbol
s=s.replace(
"""export const RESOLVER = Symbol('Awilix Resolver Config')
""",
"""export const RESOLVER = Symbol('Awilix Resolver Config')

/**
 * Symbol used to store the initializer function on a resolver, so the fluid
 * `initializer()` builder method can share the same public property name.
 */
export const INITIALIZER = Symbol('Awilix Resolver Initializer')
""")

# 2. asFunction: include INITIALIZER in result
s=s.replace(
"""  const resolve = generateResolve(fn)
  const result = {
    resolve,
    ...opts,
  }

  return createDisposableResolver(createBuildResolver(result))
}""",
"""  const resolve = generateResolve(fn)
  const result = {
    resolve,
    ...opts,
    [INITIALIZER]: (opts as any).initializer,
  }

  return createDisposableResolver(createBuildResolver(result))
}""")

# 3. asClass: include INITIALIZER in result
s=s.replace(
"""  const resolve = generateResolve(newClass, Type)
  return createDisposableResolver(
    createBuildResolver({
      ...opts,
      resolve,
    }),
  )
}""",
"""  const resolve = generateResolve(newClass, Type)
  return createDisposableResolver(
    createBuildResolver({
      ...opts,
      resolve,
      [INITIALIZER]: (opts as any).initializer,
    }),
  )
}""")

# 4. setInitializer method stores under INITIALIZER
s=s.replace(
"""  function setInitializer(this: any, initializer: Initializer<T>) {
    return createBuildResolver({
      ...this,
      initializer,
    })
  }""",
"""  function setInitializer(this: any, initializer: Initializer<T>) {
    return createBuildResolver({
      ...this,
      [INITIALIZER]: initializer,
    })
  }""")

open(p,'w').write(s)
print("resolvers patched")
PY
cd /app && grep -n "INITIALIZER" src/resolvers.ts