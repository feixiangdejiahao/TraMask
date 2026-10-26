cd /app && python3 - <<'PYEOF'
p='src/resolvers.ts'
s=open(p).read()

# BuildResolver interface with Omit
s=s.replace(
"""export interface BuildResolver<T> extends Resolver<T>, BuildResolverOptions<T> {""",
"""export interface BuildResolver<T>
  extends Omit<Resolver<T>, 'initializer'>,
    Omit<BuildResolverOptions<T>, 'initializer'> {""")

# Add initializer to BuildResolverOptions
s=s.replace(
"""export interface BuildResolverOptions<T>
  extends ResolverOptions<T>,
    DisposableResolverOptions<T> {
  /**
   * Resolution mode.
   */
  injectionMode?: InjectionModeType
  /**
   * Injector function to provide additional parameters.
   */
  injector?: InjectorFunction
}""",
"""export interface BuildResolverOptions<T>
  extends ResolverOptions<T>,
    DisposableResolverOptions<T> {
  /**
   * Resolution mode.
   */
  injectionMode?: InjectionModeType
  /**
   * Injector function to provide additional parameters.
   */
  injector?: InjectorFunction
  /**
   * Initializer function that is invoked by `container.initialize()` after
   * the instance has been resolved. May return a replacement instance.
   */
  initializer?: Initializer<T>
}""")

# asFunction: map opts.initializer to symbol
s=s.replace(
"""  opts = makeOptions(defaults, opts, (fn as any)[RESOLVER])

  const resolve = generateResolve(fn)
  const result = {
    resolve,
    ...opts,
  }

  return createDisposableResolver(createBuildResolver(result))""",
"""  opts = makeOptions(defaults, opts, (fn as any)[RESOLVER])
  if (opts.initializer) {
    ;(opts as any)[INITIALIZER] = opts.initializer
  }

  const resolve = generateResolve(fn)
  const result = {
    resolve,
    ...opts,
  }

  return createDisposableResolver(createBuildResolver(result))""")

# asClass: map opts.initializer to symbol
s=s.replace(
"""  opts = makeOptions(defaults, opts, (Type as any)[RESOLVER])

  // A function to handle object construction for us, as to make the generateResolve more reusable""",
"""  opts = makeOptions(defaults, opts, (Type as any)[RESOLVER])
  if (opts.initializer) {
    ;(opts as any)[INITIALIZER] = opts.initializer
  }

  // A function to handle object construction for us, as to make the generateResolve more reusable""")

open(p,'w').write(s)
print('done')
PYEOF
npx tsc -p tsconfig.json --noEmit --pretty false 2>&1 | grep -v "examples/typescript" | head -20