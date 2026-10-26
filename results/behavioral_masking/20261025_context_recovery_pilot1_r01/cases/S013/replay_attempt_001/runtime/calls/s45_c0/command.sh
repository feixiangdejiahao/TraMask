cd /app && python3 - <<'PY'
p='src/container.ts'
s=open(p).read()

# Remove the state declarations after rootContainer
state_block = """
  /**
   * Values that have been initialized for this container. Keyed by registration name.
   */
  const initializedValues = new Map<string | symbol, CacheEntry>()

  type InitializationState =
    | { status: 'idle' }
    | { status: 'initializing'; promise: Promise<InitializeResult> }
    | { status: 'success'; result: InitializeResult }
    | { status: 'failed'; error: Error }

  /**
   * The initialization state of this container.
   */
  let initializationState: InitializationState = { status: 'idle' }

  return container
"""
assert state_block in s
s = s.replace(state_block, "\n  return container\n")

# Insert state declarations before cradle proxy creation (after resolutionStack / registrations)
insert_after = """  // Internal registration store for this container.
  const registrations: RegistrationHash = {}

"""
state_new = """  // Internal registration store for this container.
  const registrations: RegistrationHash = {}

  /**
   * Values that have been initialized for this container. Keyed by registration name.
   */
  const initializedValues = new Map<string | symbol, CacheEntry>()

  type InitializationState =
    | { status: 'idle' }
    | { status: 'initializing'; promise: Promise<InitializeResult> }
    | { status: 'success'; result: InitializeResult }
    | { status: 'failed'; error: Error }

  /**
   * The initialization state of this container.
   */
  let initializationState: InitializationState = { status: 'idle' }

"""
assert insert_after in s
s = s.replace(insert_after, state_new, 1)

open(p,'w').write(s)
print("state moved")
PY
cd /app && npx tsc -p tsconfig.json --noEmit --pretty 2>&1 | grep -v "examples/typescript" | head -60