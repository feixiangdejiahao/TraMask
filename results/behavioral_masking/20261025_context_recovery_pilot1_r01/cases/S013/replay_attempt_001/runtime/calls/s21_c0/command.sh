cd /app && python3 - <<'PY'
p='src/resolvers.ts'
s=open(p).read()
s=s.replace(
"""  // Use a regular function instead of an arrow function to facilitate binding to the resolver.
  return function resolve<T extends object>(
    this: BuildResolver<any>,
    container: AwilixContainer<T>,
  ) {""",
"""  // Use a regular function instead of an arrow function to facilitate binding to the resolver.
  const resolve = function resolve<T extends object>(
    this: BuildResolver<any>,
    container: AwilixContainer<T>,
  ) {""", 1)
# Replace the closing `}` of generateResolve (the final return fn() } } part) to add assignment + return.
s = s.replace(
"""    return fn()
  }
}

/**
 * Parses the dependencies from the given function.""",
"""    return fn()
  }

  // Expose the parsed dependencies so initialization can build a dependency graph.
  ;(resolve as any).dependencies = dependencies

  return resolve
}

/**
 * Parses the dependencies from the given function.""", 1)
open(p,'w').write(s)
print("patched")
PY
nl -ba src/resolvers.ts | sed -n '478,530p'