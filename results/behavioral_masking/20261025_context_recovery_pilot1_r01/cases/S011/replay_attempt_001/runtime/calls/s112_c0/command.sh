cd /app && git add CHANGELOG.md README.md src/awilix.ts src/container.ts src/errors.ts src/resolvers.ts src/__tests__/initialize.test.ts && git commit -m "feat: add asynchronous initialization with dependency-aware startup ordering

Add container.initialize() and resolver.initializer() support. Services with
initializers are organized into dependency levels, initialized level by level
with configurable concurrency, and rolled back (disposed in reverse order) if
any initializer fails. Also add AwilixInitializationError and
AwilixNotInitializedError, and prevent resolving uninitialized services." 2>&1 | tail -10