cd /app/libs/core && python - <<'PY'
p = 'langchain_core/runnables/coalesce.py'
s = open(p).read()
s = s.replace('''            import threading, time
            print("DEBUG run_one", input_, threading.get_ident(), flush=True)
            time.sleep(0.05)
            if self.backend.register(input_):''',
'''            import threading, time
            print("DEBUG run_one", input_, threading.get_ident(), "self", id(self), "backend", id(self.backend), flush=True)
            time.sleep(0.05)
            if self.backend.register(input_):''')
open(p,'w').write(s)
PY
cd /app/libs/core && timeout 15 python /tmp/debug.py