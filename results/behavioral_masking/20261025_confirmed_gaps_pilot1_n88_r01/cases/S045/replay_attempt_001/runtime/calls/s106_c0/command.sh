cd /app/libs/core && python - <<'PY'
p = 'langchain_core/runnables/coalesce.py'
s = open(p).read()
s = s.replace('''        for waiter in async_waiters:
            waiter.result = result
            waiter.error = error
            waiter.loop.call_soon_threadsafe(waiter.event.set)''',
'''        for waiter in async_waiters:
            waiter.result = result
            waiter.error = error
            try:
                waiter.loop.call_soon_threadsafe(waiter.event.set)
            except RuntimeError:
                # The waiter's event loop is already closed.
                pass''')
s = s.replace('''                for waiter in execution.async_waiters:
                    waiter.cancelled = True
                    waiter.loop.call_soon_threadsafe(waiter.event.set)''',
'''                for waiter in execution.async_waiters:
                    waiter.cancelled = True
                    try:
                        waiter.loop.call_soon_threadsafe(waiter.event.set)
                    except RuntimeError:
                        # The waiter's event loop is already closed.
                        pass''')
open(p,'w').write(s)
print("guarded")
PY
cd /app/libs/core && timeout 90 python /tmp/test_coalesce.py 2>&1 | tail -5 && timeout 60 python /tmp/test_coalesce_edge.py 2>&1 | tail -5