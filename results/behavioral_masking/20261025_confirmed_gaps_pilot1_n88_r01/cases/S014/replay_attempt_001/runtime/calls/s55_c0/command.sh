cd /app && python3 - <<'PY'
p='packages/core/test/prompts/async-autocomplete.test.ts'
s=open(p).read()

# fix stale option
s=s.replace("resolvers.get('')!([{ value: 'stale' }]);", "resolvers.get('')!([{ value: 'stale', label: 'Stale' }]);")

# fix cache test
old = '''\t\tinstance.prompt();
\t\t// type 'a' -> fetch
\t\tinput.emit('keypress', 'a', { name: 'a' });
\t\tawait new Promise((r) => setTimeout(r, 250));
\t\texpect(calls).toBe(2);
\t\t// clear input -> fetch ''
\t\tinput.emit('keypress', '\\u007f', { name: 'backspace' });
\t\tawait new Promise((r) => setTimeout(r, 250));
\t\texpect(calls).toBe(3);
\t\t// type 'a' again -> cache hit, no fetch
\t\tinput.emit('keypress', 'a', { name: 'a' });
\t\tawait new Promise((r) => setTimeout(r, 50));
\t\texpect(calls).toBe(3);
\t\texpect(instance.filteredOptions).toEqual([{ value: 'apple', label: 'Apple' }]);
\t\tinstance.clearCache();
\t\tinput.emit('keypress', '\\u007f', { name: 'backspace' });
\t\tinput.emit('keypress', 'a', { name: 'a' });
\t\tawait new Promise((r) => setTimeout(r, 250));
\t\texpect(calls).toBe(5);'''
new = '''\t\tinstance.prompt();
\t\t// type 'a' -> fetch
\t\tinput.emit('keypress', 'a', { name: 'a' });
\t\tawait new Promise((r) => setTimeout(r, 250));
\t\texpect(calls).toBe(2);
\t\t// clear input -> cached '' from initial fetch, no fetch
\t\tinput.emit('keypress', '\\u007f', { name: 'backspace' });
\t\tawait new Promise((r) => setTimeout(r, 250));
\t\texpect(calls).toBe(2);
\t\t// type 'a' again -> cache hit, no fetch
\t\tinput.emit('keypress', 'a', { name: 'a' });
\t\tawait new Promise((r) => setTimeout(r, 50));
\t\texpect(calls).toBe(2);
\t\texpect(instance.filteredOptions).toEqual([{ value: 'apple', label: 'Apple' }]);
\t\t// clearCache forces refetch of the next searches
\t\tinstance.clearCache();
\t\tinput.emit('keypress', '\\u007f', { name: 'backspace' });
\t\tawait new Promise((r) => setTimeout(r, 250));
\t\texpect(calls).toBe(3);
\t\tinput.emit('keypress', 'a', { name: 'a' });
\t\tawait new Promise((r) => setTimeout(r, 250));
\t\texpect(calls).toBe(4);'''
assert old in s, "cache test block not found"
s=s.replace(old,new)
open(p,'w').write(s)
print("test updated")
PY
cd /app && npx tsc --noEmit 2>&1 | grep -v "npm warn" | head