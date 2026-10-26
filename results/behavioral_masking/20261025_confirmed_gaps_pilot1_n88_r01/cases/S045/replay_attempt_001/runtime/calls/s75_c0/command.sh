cd /app/libs/core && python - <<'PY'
p = 'langchain_core/runnables/coalesce.py'
s = open(p).read()
s = s.replace('''        def run_one(input_: Input, cfg: RunnableConfig) -> Output | Exception:
            import threading, time
            print("DEBUG run_one", input_, threading.get_ident(), "self", id(self), "backend", id(self.backend), flush=True)
            time.sleep(0.05)
            if self.backend.register(input_):''',
'''        def run_one(input_: Input, cfg: RunnableConfig) -> Output | Exception:
            if self.backend.register(input_):''')
open(p,'w').write(s)
print("cleaned")
PY
cd /app/libs/core && timeout 15 python /tmp/debug.py