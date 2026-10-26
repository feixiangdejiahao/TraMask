cd /app && python - <<'PYEOF'
path = 'pwnlib/tubes/mux.py'
s = open(path).read()

# Add helper in TubeMultiplexer after __init__ or before open_channel
helper = '''
    def _resolve_timeout(self, timeout):
        """Resolve a timeout argument, honouring Timeout.default."""
        if timeout is Timeout.default:
            return self._underlying.timeout
        return timeout

'''
marker = '''    # ------------------------------------------------------------------
    # Public properties
    # ------------------------------------------------------------------
'''
assert marker in s
s = s.replace(marker, helper + marker, 1)

# open_channel: use resolved timeout in wait
old = '''        if not channel._open_event.wait(timeout):
'''
new = '''        if not channel._open_event.wait(self._resolve_timeout(timeout)):
'''
assert old in s
s = s.replace(old, new, 1)

# accept_channel: resolve timeout
old = '''        deadline = None if timeout is None else time.time() + timeout
'''
new = '''        timeout = self._resolve_timeout(timeout)
        deadline = None if timeout is None else time.time() + timeout
'''
assert old in s
s = s.replace(old, new, 1)

open(path,'w').write(s)
print("timeout default handled")
PYEOF
python -c "import ast; ast.parse(open('/app/pwnlib/tubes/mux.py').read()); print('ok')"