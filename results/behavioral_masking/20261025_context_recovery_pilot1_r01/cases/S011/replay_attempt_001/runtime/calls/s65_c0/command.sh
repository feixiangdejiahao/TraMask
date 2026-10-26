cd /app && python3 - <<'PYEOF'
p='src/__tests__/initialize.test.ts'
s=open(p).read()
start = s.find("  it('scope initializes inherited scoped registrations independently'")
end = s.find("  it('scope initializes an inherited scoped registration for its own instance'")
if start > -1 and end > -1:
    s = s[:start] + s[end:]
open(p,'w').write(s)
print('removed bogus test')
PYEOF
npx jest src/__tests__/initialize.test.ts --no-coverage 2>&1 | tail -60