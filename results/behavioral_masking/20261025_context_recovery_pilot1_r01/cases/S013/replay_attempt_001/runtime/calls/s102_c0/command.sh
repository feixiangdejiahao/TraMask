cd /app && git add README.md src/awilix.ts src/container.ts src/errors.ts src/resolvers.ts src/__tests__/container.initialize.test.ts && git commit -m "feat: add asynchronous container initialization with dependency-aware ordering

Add support for registering an initializer on asFunction/asClass resolvers
and initializing the container with container.initialize({ concurrency }).

- Add .initializer() fluid API and initializer resolver option
- Initialize registrations in dependency levels, running each level in
  parallel with the configured concurrency
- Return totalDuration and per-registration duration/level metrics
- Roll back already-initialized services in reverse order when an
  initializer fails, waiting for in-flight initializers in the level
- Throw AwilixNotInitializedError when resolving uninitialized services
- Throw AwilixInitializationError with err.cause on initialization failure
- Make initialize() idempotent after success; reject on re-init after failure
- Detect circular dependencies during graph construction without entering
  a failed state
- Support independent initialization of scoped containers without
  reinitializing parent singletons" && git log --oneline -3 && git status --short