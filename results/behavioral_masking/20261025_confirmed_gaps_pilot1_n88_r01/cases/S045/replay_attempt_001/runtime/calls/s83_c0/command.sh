cd /app/libs/core && python - <<'PY'
p = 'langchain_core/runnables/coalesce.py'
s = open(p).read()
s = s.replace('''        with self._lock:
            execution = self._executions.get(ckey)
            self._total += 1
            if execution is None or execution.completed or execution.cancelled:
                self._executions[ckey] = _Execution()
                self._active += 1
                return True
            self._coalesced += 1
            return False''',
'''        with self._lock:
            execution = self._executions.get(ckey)
            self._total += 1
            import threading as _t
            print("INSIDE register", _t.get_ident(), "key", ckey, "execs", list(self._executions.keys()), "active", self._active, "exec", execution, flush=True)
            if execution is None or execution.completed or execution.cancelled:
                self._executions[ckey] = _Execution()
                self._active += 1
                return True
            self._coalesced += 1
            return False''')
open(p,'w').write(s)
PY
cd /app/libs/core && timeout 15 python /tmp/debug.py 2>&1 | grep -E "INSIDE register|post barrier|out:|stats" | head -40