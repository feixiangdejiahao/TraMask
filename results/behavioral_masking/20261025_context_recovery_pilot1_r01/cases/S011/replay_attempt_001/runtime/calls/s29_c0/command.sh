cat > /tmp/awilix_patch.py <<'PYEOF'
p='src/awilix.ts'
s=open(p).read()
s=s.replace(
"""export {
  type AwilixContainer,
  type ContainerOptions,
  type CacheEntry,
  type ClassOrFunctionReturning,
  type FunctionReturning,
  type NameAndRegistrationPair,
  type RegistrationHash,
  type ResolveOptions,
  createContainer,
} from './container'""",
"""export {
  type AwilixContainer,
  type ContainerOptions,
  type CacheEntry,
  type ClassOrFunctionReturning,
  type FunctionReturning,
  type NameAndRegistrationPair,
  type RegistrationHash,
  type ResolveOptions,
  type InitializeOptions,
  type InitializationResult,
  type ServiceMetrics,
  createContainer,
} from './container'""")
s=s.replace(
"""export {
  AwilixError,
  AwilixRegistrationError,
  AwilixResolutionError,
  AwilixTypeError,
} from './errors'""",
"""export {
  AwilixError,
  AwilixInitializationError,
  AwilixNotInitializedError,
  AwilixRegistrationError,
  AwilixResolutionError,
  AwilixTypeError,
} from './errors'""")
s=s.replace(
"""export {
  type BuildResolverOptions,
  type Disposer,
  type InjectorFunction,
  type Resolver,
  type ResolverOptions,
  type BuildResolver,
  type Constructor,
  type DisposableResolver,
  type DisposableResolverOptions,
  RESOLVER,
  aliasTo,
  asClass,
  asFunction,
  asValue,
  createBuildResolver,
  createDisposableResolver,
} from './resolvers'""",
"""export {
  type BuildResolverOptions,
  type Disposer,
  type Initializer,
  type InjectorFunction,
  type Resolver,
  type ResolverOptions,
  type BuildResolver,
  type Constructor,
  type DisposableResolver,
  type DisposableResolverOptions,
  RESOLVER,
  aliasTo,
  asClass,
  asFunction,
  asValue,
  createBuildResolver,
  createDisposableResolver,
  getDependencies,
} from './resolvers'""")
open(p,'w').write(s)
print('awilix patch done')
PYEOF
python3 /tmp/awilix_patch.py
cat src/awilix.ts