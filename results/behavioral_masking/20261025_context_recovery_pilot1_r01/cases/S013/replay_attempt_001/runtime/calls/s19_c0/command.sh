cd /app && python3 - <<'PY'
p='src/awilix.ts'
s=open(p).read()
s=s.replace(
"""  type FunctionReturning,
  type NameAndRegistrationPair,
  type RegistrationHash,
  type ResolveOptions,
  createContainer,
} from './container'""",
"""  type FunctionReturning,
  type InitializeMetrics,
  type InitializeOptions,
  type InitializeResult,
  type NameAndRegistrationPair,
  type RegistrationHash,
  type ResolveOptions,
  createContainer,
} from './container'""")
s=s.replace(
"""  AwilixError,
  AwilixRegistrationError,
  AwilixResolutionError,
  AwilixTypeError,
} from './errors'""",
"""  AwilixError,
  AwilixInitializationError,
  AwilixNotInitializedError,
  AwilixRegistrationError,
  AwilixResolutionError,
  AwilixTypeError,
} from './errors'""")
s=s.replace(
"""  type BuildResolverOptions,
  type Disposer,
  type InjectorFunction,""",
"""  type BuildResolverOptions,
  type Disposer,
  type Initializer,
  type InjectorFunction,""")
open(p,'w').write(s)
print(open(p).read())
PY