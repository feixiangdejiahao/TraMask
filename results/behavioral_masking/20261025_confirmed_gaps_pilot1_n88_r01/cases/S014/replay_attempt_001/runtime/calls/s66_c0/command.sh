cd /app && python3 - <<'PY'
p='packages/core/test/prompts/async-autocomplete.test.ts'
s=open(p).read()
old = '''\t\tinstance.prompt();
\t\t// initial '' fetch
\t\texpect(signals.length).toBe(1);
\t\tinput.emit('keypress', 'a', { name: 'a' });
\t\tawait vi.advanceTimersByTimeAsync(20);
\t\t// 'a' fetch in flight; resolve and cache it
\t\tresolvers.get('a')!([{ value: 'apple', label: 'Apple' }]);
\t\tawait Promise.resolve();
\t\t// backspace -> cached '' hit
\t\tinput.emit('keypress', '\\u007f', { name: 'backspace' });
\t\t// type 'b' -> in-flight fetch
\t\tinput.emit('keypress', 'b', { name: 'b' });
\t\tawait vi.advanceTimersByTimeAsync(20);
\t\tconst bSignal = signals[signals.length - 1];
\t\texpect(instance.loading).toBe(true);
\t\t// backspace -> cached '' hit should abort in-flight 'b' and apply cache
\t\tinput.emit('keypress', '\\u007f', { name: 'backspace' });
\t\texpect(bSignal.aborted).toBe(true);
\t\texpect(instance.loading).toBe(false);
\t\texpect(instance.filteredOptions).toEqual(fruits);'''
new = '''\t\tinstance.prompt();
\t\t// initial '' fetch; resolve and cache it
\t\texpect(signals.length).toBe(1);
\t\tresolvers.get('')!([{ value: 'empty', label: 'Empty' }]);
\t\tawait Promise.resolve();
\t\t// type 'a' -> fetch; resolve and cache it
\t\tinput.emit('keypress', 'a', { name: 'a' });
\t\tawait vi.advanceTimersByTimeAsync(20);
\t\tresolvers.get('a')!([{ value: 'apple', label: 'Apple' }]);
\t\tawait Promise.resolve();
\t\t// backspace -> cached '' hit
\t\tinput.emit('keypress', '\\u007f', { name: 'backspace' });
\t\t// type 'b' -> in-flight fetch
\t\tinput.emit('keypress', 'b', { name: 'b' });
\t\tawait vi.advanceTimersByTimeAsync(20);
\t\tconst bSignal = signals[signals.length - 1];
\t\texpect(instance.loading).toBe(true);
\t\t// backspace -> cached '' hit should abort in-flight 'b' and apply cache
\t\tinput.emit('keypress', '\\u007f', { name: 'backspace' });
\t\texpect(bSignal.aborted).toBe(true);
\t\texpect(instance.loading).toBe(false);
\t\texpect(instance.filteredOptions).toEqual(fruits);'''
assert old in s
s=s.replace(old,new)
open(p,'w').write(s)
print("fixed")
PY
cd /app/packages/core && npx vitest run test/prompts/async-autocomplete.test.ts 2>&1 | tail -12