cd /app/libs/core && python - <<'PY'
p = 'langchain_core/runnables/coalesce.py'
s = open(p).read()
s = s.replace('''            r = self.backend.register(input_)
            print("DEBUG register result", input_, r, flush=True)
            if r:''',
'''            r = self.backend.register(input_)
            print("DEBUG register result", input_, r, "execs_after", list(self.backend._executions.keys()), "active", self.backend._active, flush=True)
            if r:''')
open(p,'w').write(s)
PY
cd /app/libs/core && timeout 15 python /tmp/debug.py 2>&1 | head -40