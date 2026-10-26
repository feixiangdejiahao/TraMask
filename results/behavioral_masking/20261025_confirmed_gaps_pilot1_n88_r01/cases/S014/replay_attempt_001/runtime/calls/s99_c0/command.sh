cd /app && python3 - <<'PY'
p='packages/core/test/prompts/async-autocomplete.test.ts'
s=open(p).read()
old = '''\t\t// retry for '' is pending; type 'a' -> debounced fetch for 'a'
\t\tinput.emit('keypress', 'a', { name: 'a' });
\t\tawait vi.advanceTimersByTimeAsync(10);
\t\texpect(searches).toEqual(['', 'a']);
\t\t// old retry timer must not fire for ''
\t\tawait vi.advanceTimersByTimeAsync(500);
\t\texpect(searches).toEqual(['', 'a']);'''
new = '''\t\t// retry for '' is pending; type 'a' -> debounced fetch for 'a'
\t\tinput.emit('keypress', 'a', { name: 'a' });
\t\tawait vi.advanceTimersByTimeAsync(10);
\t\texpect(searches).toEqual(['', 'a']);
\t\t// old '' retry was scheduled for t=100ms; it must not fire
\t\tawait vi.advanceTimersByTimeAsync(95);
\t\texpect(searches).toEqual(['', 'a']);
\t\t// 'a' retry (scheduled after its own failure at t=110ms) is allowed to fire
\t\tawait vi.advanceTimersByTimeAsync(10);
\t\texpect(searches).toEqual(['', 'a', 'a']);'''
assert old in s
s=s.replace(old,new)
open(p,'w').write(s)
print("done")
PY
cd /app/packages/core && npx vitest run test/prompts/async-autocomplete.test.ts 2>&1 | tail -8