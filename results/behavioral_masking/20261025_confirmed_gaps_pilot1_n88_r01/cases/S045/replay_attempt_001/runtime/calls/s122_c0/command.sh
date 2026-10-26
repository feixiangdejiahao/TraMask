cd /app/libs/core && python - <<'PY'
p = 'langchain_core/runnables/coalesce.py'
s = open(p).read()
old = '''        with self._lock:
            for execution in self._executions.values():
                execution.cancelled = True
                for waiter in execution.sync_waiters:
                    waiter.cancelled = True
                    waiter.event.set()
                for waiter in execution.async_waiters:
                    waiter.cancelled = True
                    try:
                        waiter.loop.call_soon_threadsafe(waiter.event.set)
                    except RuntimeError:
                        # The waiter's event loop is already closed.
                        pass
                execution.sync_waiters = []
                execution.async_waiters = []
            self._executions.clear()
            self._active = 0
            self._coalesced = 0
            self._total = 0'''
new = '''        with self._lock:
            for execution in self._executions.values():
                execution.cancelled = True
                for waiter in execution.sync_waiters:
                    waiter.cancelled = True
                    waiter.event.set()
                for waiter in execution.async_waiters:
                    waiter.cancelled = True
                    try:
                        waiter.loop.call_soon_threadsafe(waiter.event.set)
                    except RuntimeError:
                        # The waiter's event loop is already closed.
                        pass
                execution.sync_waiters = []
                execution.async_waiters = []
            # Keep the cancelled executions so that late joiners raise
            # `asyncio.CancelledError` instead of `KeyError`. The next `register`
            # for a key treats a cancelled execution as fresh and replaces it.
            self._active = 0
            self._coalesced = 0
            self._total = 0'''
assert old in s
s = s.replace(old, new, 1)
open(p,'w').write(s)
print("updated clear")
PY
cd /app/libs/core && timeout 90 python /tmp/test_coalesce.py 2>&1 | tail -4 && timeout 60 python /tmp/test_coalesce_edge.py 2>&1 | tail -3