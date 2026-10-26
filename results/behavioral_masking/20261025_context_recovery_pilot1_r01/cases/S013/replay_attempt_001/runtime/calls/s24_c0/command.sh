cd /app && python3 - <<'PY'
p='src/container.ts'
s=open(p).read()

s=s.replace(
"""import {
  AwilixRegistrationError,
  AwilixResolutionError,
  AwilixTypeError,
} from './errors'""",
"""import {
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
  Initializer,
  Resolver,
  asClass,
  asFunction,
} from './resolvers'""")

open(p,'w').write(s)
print("imports patched")
PY