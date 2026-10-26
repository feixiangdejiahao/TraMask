cd /app/libs/core && python - <<'PY'
p = 'langchain_core/runnables/coalesce.py'
s = open(p).read()
s = s.replace('''        def run_one(input_: Input, cfg: RunnableConfig) -> Output | Exception:
            if self.backend.register(input_):''',
'''        import threading
        barrier = threading.Barrier(len(inputs))
        def run_one(input_: Input, cfg: RunnableConfig) -> Output | Exception:
            print("DEBUG pre barrier", input_, flush=True)
            barrier.wait(timeout=5)
            print("DEBUG post barrier", input_, flush=True)
            if self.backend.register(input_):''')
open(p,'w').write(s)
PY
cd /app/libs/core && timeout 15 python /tmp/debug.py 2>&1 | head -30