cd /app && python3 - <<'PY'
p='README.md'
s=open(p).read()

# 1. Resolver options
s=s.replace(
"""- `injector`: An injector function - see
  [Per-module local injections](#per-module-local-injections)
- `register`: Only used in `loadModules`, determines how to register a loaded
  module explicitly""",
"""- `injector`: An injector function - see
  [Per-module local injections](#per-module-local-injections)
- `initializer`: An async function called with the resolved instance during
  `container.initialize()`. It may return a replacement instance.
- `register`: Only used in `loadModules`, determines how to register a loaded
  module explicitly""")

# 2. asFunction chainable API - add initializer
s=s.replace(
"""- `asFunction(fn).inject(injector: Function)`: Let's you provide local
  dependencies only available to this module. The `injector` gets the container
  passed as the first and only argument and should return an object.""",
"""- `asFunction(fn).inject(injector: Function)`: Let's you provide local
  dependencies only available to this module. The `injector` gets the container
  passed as the first and only argument and should return an object.
- `asFunction(fn).initializer(initializer: Function)`: Registers an async
  initializer that is called with the resolved instance during
  `container.initialize()`. It may return a replacement instance.""")

# 3. Add initialize section after dispose section (before Universal Module)
marker = """# Universal Module (Browser Support)"""
init_section = """## Initializing the container

Registrations created with `asFunction()` or `asClass()` can be given an
`initializer` function. The container can then be initialized asynchronously;
all initializers are run in dependency order, organized into levels where all
services at a level complete before the next level begins. Within a level,
initializers run in parallel (bounded by the `concurrency` option).

```js
const container = createContainer()

container.register({
  database: asClass(DatabasePool)
    .singleton()
    .initializer(async (instance) => {
      await instance.connect()
      return instance
    }),
})

const result = await container.initialize({ concurrency: 5 })
console.log(result.totalDuration)
console.log(result.metrics.database.duration)
console.log(result.metrics.database.level)
```

Once initialized, the container is considered initialized and calling
`initialize()` again returns immediately. Resolving a registration with an
`initializer` before it has been initialized throws an
`AwilixNotInitializedError`. If an initializer throws or rejects, all already
initialized services are disposed in reverse order and an
`AwilixInitializationError` is thrown (the original error is available via
`err.cause`).

Scoped containers can be initialized independently; parent container singletons
are not reinitialized.

# Universal Module (Browser Support)"""
assert marker in s
s=s.replace(marker, init_section, 1)

open(p,'w').write(s)
print("README updated")
PY
cd /app && git diff --stat README.md