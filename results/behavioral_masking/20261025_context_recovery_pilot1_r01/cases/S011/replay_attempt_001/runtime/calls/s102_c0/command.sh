cd /app && python3 - <<'PYEOF'
p='src/resolvers.ts'
s=open(p).read()
s=s.replace(
"""export interface BuildResolver<T>
  extends Omit<Resolver<T>, 'initializer'>,
    Omit<BuildResolverOptions<T>, 'initializer'> {""",
"""export interface BuildResolver<T>
  extends Resolver<T>,
    Omit<BuildResolverOptions<T>, 'initializer'> {""")
open(p,'w').write(s)
print('simplified')
PYEOF
npx tsc -p tsconfig.json --noEmit --pretty false 2>&1 | grep -v "examples/typescript" | head