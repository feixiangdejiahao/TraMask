cd /app/libs/core && python - <<'PY'
p = 'langchain_core/runnables/coalesce.py'
s = open(p).read()
s = s.replace('''        with self._lock:
            execution = self._executions.get(ckey)
            self._total += 1
            if execution is None or execution.completed or execution.cancelled:''',
'''        with self._lock:
            execution = self._executions.get(ckey)
            self._total += 1
            print("DEBUG register", ckey, "exec", execution, "completed", getattr(execution, "completed", None), "active", self._active, "execs", list(self._executions.keys()), flush=True)
            if execution is None or execution.completed or execution.cancelled:''')
open(p,'w').write(s)
PY
cd /app/libs/core && timeout 15 python /tmp/debug.py 2>&1 | head -20