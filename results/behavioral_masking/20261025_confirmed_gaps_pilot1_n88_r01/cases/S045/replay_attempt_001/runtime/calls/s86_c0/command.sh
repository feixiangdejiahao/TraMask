cd /app/libs/core && python - <<'PY'
p = 'langchain_core/runnables/coalesce.py'
s = open(p).read()
s = s.replace('''            if execution is None or execution.completed or execution.cancelled:
                self._executions[ckey] = _Execution()
                self._active += 1
                return True''',
'''            if execution is None or execution.completed or execution.cancelled:
                self._executions[ckey] = _Execution()
                self._active += 1
                print("STORED", _t.get_ident(), "ckey", repr(ckey), "stored key repr", repr(list(self._executions.keys())[-1]), "type", type(list(self._executions.keys())[-1]), "dict id", id(self._executions), flush=True)
                return True''')
open(p,'w').write(s)
PY
cd /app/libs/core && timeout 15 python /tmp/debug.py 2>&1 | grep -E "STORED|INSIDE register" | head -20