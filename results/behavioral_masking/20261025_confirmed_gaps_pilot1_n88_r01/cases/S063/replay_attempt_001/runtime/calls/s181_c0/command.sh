cd /app && python - <<'PYEOF'
path = 'pwnlib/tubes/mux.py'
s = open(path).read()

old = '''    def _maybe_pause(self, channel):
        send = False
        with channel._recv_cond:
            total = channel._recv_size + len(channel.buffer)
            if not channel._flow_paused and \\
                    total > self._high_water_mark:
                channel._flow_paused = True
                send = True
'''
new = '''    def _maybe_pause(self, channel):
        send = False
        high = channel.buffer.high_water
        if high is None:
            high = self._high_water_mark
        with channel._recv_cond:
            total = channel._recv_size + len(channel.buffer)
            if not channel._flow_paused and \\
                    total > high:
                channel._flow_paused = True
                send = True
'''
assert old in s
s = s.replace(old, new, 1)

old = '''    def _maybe_resume(self, channel):
        send = False
        with channel._recv_cond:
            total = channel._recv_size + len(channel.buffer)
            if channel._flow_paused and \\
                    total <= self._low_water_mark:
                channel._flow_paused = False
                send = True
'''
new = '''    def _maybe_resume(self, channel):
        send = False
        low = channel.buffer.low_water
        if low is None:
            low = self._low_water_mark
        with channel._recv_cond:
            total = channel._recv_size + len(channel.buffer)
            if channel._flow_paused and \\
                    total <= low:
                channel._flow_paused = False
                send = True
'''
assert old in s
s = s.replace(old, new, 1)

open(path,'w').write(s)
print("flow control respects channel buffer watermarks")
PYEOF
python -c "import ast; ast.parse(open('/app/pwnlib/tubes/mux.py').read()); print('ok')"