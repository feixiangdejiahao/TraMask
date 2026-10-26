cd /app/libs/core && python - <<'PY'
p = 'langchain_core/runnables/coalesce.py'
s = open(p).read()
s = s.replace("""        def run_one(input_: Input, cfg: RunnableConfig) -> Output | Exception:
            if self.backend.register(input_):""",
"""        def run_one(input_: Input, cfg: RunnableConfig) -> Output | Exception:
            print("DEBUG run_one", input_, flush=True)
            if self.backend.register(input_):""")
open(p,'w').write(s)
PY
cd /app/libs/core && timeout 15 python /tmp/debug.py