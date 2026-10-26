cd /app && python3 - <<'PY'
p='src/kea/kea.ts'
s=open(p).read()
old = """  if (getContext().options.proxyFields) {
    proxyFields(wrapper)
  }

  return wrapper
"""
new = """  if (getContext().options.atomicSelectors) {
    wrapper.selectorHealth = () => wrapper.build().selectorHealth!()
  }

  if (getContext().options.proxyFields) {
    proxyFields(wrapper)
  }

  return wrapper
"""
assert old in s
s=s.replace(old,new)
open(p,'w').write(s)
print('kea updated')
PY
grep -n "selectorHealth" src/kea/kea.ts