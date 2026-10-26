cd /app && python3 - <<'PY'
p='src/container.ts'
s=open(p).read()

s=s.replace(
"""        throw new AwilixResolutionError(name, resolutionStack)
      }

      const lifetime = resolver.lifetime || Lifetime.TRANSIENT
""",
"""        throw new AwilixResolutionError(name, resolutionStack)
      }

      // If this registration has an initializer, it must be initialized before it can be
      // resolved. If it has already been initialized, return the initialized value.
      if (typeof (resolver as any).initializer === 'function') {
        const initializedEntry = findInitializedValue(name)
        if (initializedEntry !== undefined) {
          return initializedEntry.value
        }
        throw new AwilixNotInitializedError(name)
      }

      const lifetime = resolver.lifetime || Lifetime.TRANSIENT
""")

open(p,'w').write(s)
print("resolve patched")
PY