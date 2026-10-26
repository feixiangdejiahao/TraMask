cd /app && python3 - <<'PY'
p='src/resolvers.ts'
s=open(p).read()

# Add InitializerResolver interface after Initializer type
s=s.replace(
"""export type Initializer<T> = (instance: T) => T | Promise<T>
""",
"""export type Initializer<T> = (instance: T) => T | Promise<T>

/**
 * A resolver that supports the `initializer()` fluid API.
 */
export interface InitializerResolver<T> {
  initializer(initializer: Initializer<T>): this
}
""", 1)

# Change BuildResolver interface
s=s.replace(
"""export interface BuildResolver<T> extends Resolver<T>, BuildResolverOptions<T> {
  injectionMode?: InjectionModeType
  injector?: InjectorFunction
  setLifetime(lifetime: LifetimeType): this
  setInjectionMode(mode: InjectionModeType): this
  singleton(): this
  scoped(): this
  transient(): this
  proxy(): this
  classic(): this
  inject(injector: InjectorFunction): this
  initializer(initializer: Initializer<T>): this
}""",
"""export interface BuildResolver<T>
  extends Resolver<T>,
    DisposableResolverOptions<T>,
    InitializerResolver<T> {
  injectionMode?: InjectionModeType
  injector?: InjectorFunction
  setLifetime(lifetime: LifetimeType): this
  setInjectionMode(mode: InjectionModeType): this
  singleton(): this
  scoped(): this
  transient(): this
  proxy(): this
  classic(): this
  inject(injector: InjectorFunction): this
}""")

open(p,'w').write(s)
print("resolvers patched")
PY
cd /app && npx tsc -p tsconfig.json --noEmit --pretty 2>&1 | head -80