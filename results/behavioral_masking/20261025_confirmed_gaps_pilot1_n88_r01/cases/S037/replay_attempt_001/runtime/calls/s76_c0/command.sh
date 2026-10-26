cd /app && python3 - <<'PY'
p='test/jest/atomic-selectors.js'
s=open(p).read()
marker = "  test('re-evaluates selectors when props change', () => {"
addition = '''  test('selectors default props to logic.props when called without them', () => {
    const logic = kea({
      selectors: () => ({
        id: [(s, p) => [p.id], (id) => id],
      }),
    })
    const built = logic({ id: 7 })
    built.mount()
    // `useSelector` calls selectors with only state
    expect(built.selectors.id(built.selector(getContext().store.getState()))).toBe(7)
    expect(built.selectors.id()).toBe(7)
  })

'''
assert marker in s
s=s.replace(marker, addition + marker)
open(p,'w').write(s)
print('test added')
PY
NODE_ENV=development BABEL_ENV=test npx jest test/jest/atomic-selectors.js -t "default props" 2>&1 | tail -20