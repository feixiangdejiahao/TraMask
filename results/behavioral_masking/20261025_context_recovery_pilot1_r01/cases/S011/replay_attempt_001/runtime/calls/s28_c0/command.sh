cat > /tmp/fix.py <<'PYEOF'
# fix resolvers BuildResolver interface
p='src/resolvers.ts'
s=open(p).read()
s=s.replace(
"""export interface BuildResolver<T> extends Resolver<T>, BuildResolverOptions<T> {""",
"""export interface BuildResolver<T>
  extends Omit<Resolver<T>, 'initializer'>,
    Omit<BuildResolverOptions<T>, 'initializer'> {""")
open(p,'w').write(s)

# fix container current typing
p='src/container.ts'
s=open(p).read()
s=s.replace(
"""    const levels: Array<Array<string | symbol>> = []
    let current = names.filter((name) => (inDegree.get(name) ?? 0) === 0)""",
"""    const levels: Array<Array<string | symbol>> = []
    let current: Array<string | symbol> = names.filter(
      (name) => (inDegree.get(name) ?? 0) === 0,
    )""")
open(p,'w').write(s)
print('fix done')
PYEOF
python3 /tmp/fix.py
npx tsc -p tsconfig.json --noEmit --pretty false 2>&1 | grep -v "examples/typescript" | head -30