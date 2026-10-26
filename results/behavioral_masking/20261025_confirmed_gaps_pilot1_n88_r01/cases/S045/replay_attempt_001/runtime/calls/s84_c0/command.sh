cd /app/libs/core && python - <<'PY'
p = 'langchain_core/runnables/coalesce.py'
s = open(p).read()
s = s.replace('''            print("INSIDE register", _t.get_ident(), "key", ckey, "execs", list(self._executions.keys()), "active", self._active, "exec", execution, flush=True)''',
'''            keys = list(self._executions.keys())
            print("INSIDE register", _t.get_ident(), "key", repr(ckey), "type", type(ckey), "execs", [repr(k) for k in keys], "active", self._active, "exec", execution, "match", any(ckey == k for k in keys), flush=True)''')
open(p,'w').write(s)
PY
cd /app/libs/core && timeout 15 python /tmp/debug.py 2>&1 | grep "INSIDE register" | sort | head -10