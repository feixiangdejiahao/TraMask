cd /app && cat >> src/errors.ts <<'EOF'

/**
 * Error thrown when resolving a registration that has an initializer
 * but the container has not been initialized (or that registration was
 * not initialized).
 */
export class AwilixNotInitializedError extends AwilixError {
  /**
   * Constructor.
   *
   * @param {string|symbol} name
   * The name of the registration that was not initialized.
   */
  constructor(name: string | symbol) {
    super(
      `'${name.toString()}' was not initialized. Please call initialize() before resolving it.`,
    )
  }
}

/**
 * Error thrown when an initializer throws or rejects during `container.initialize()`.
 * The original error is available via `err.cause`.
 */
export class AwilixInitializationError extends AwilixError {
  /**
   * The original error that caused the initialization to fail.
   */
  cause: Error

  /**
   * Constructor.
   *
   * @param {string|symbol} name
   * The name of the registration that failed to initialize.
   *
   * @param {Error} cause
   * The original error thrown/rejected by the initializer.
   */
  constructor(name: string | symbol, cause: Error) {
    super(
      `Failed to initialize '${name.toString()}': ${cause.message}`,
    )
    this.cause = cause
  }
}
EOF
echo "done"