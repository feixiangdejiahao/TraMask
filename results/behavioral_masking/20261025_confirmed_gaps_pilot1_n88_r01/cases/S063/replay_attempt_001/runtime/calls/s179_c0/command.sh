cd /app && python - <<'PYEOF'
path = 'pwnlib/tubes/mux.py'
s = open(path).read()

old = '''    def _maybe_pause(self, channel):
        send = False
        with channel._recv_cond:
            if not channel._flow_paused and \\
                    channel._recv_size > self._high_water_mark:
                channel._flow_paused = True
                send = True
'''
new = '''    def _maybe_pause(self, channel):
        send = False
        with channel._recv_cond:
            total = channel._recv_size + len(channel.buffer)
            if not channel._flow_paused and \\
                    total > self._high_water_mark:
                channel._flow_paused = True
                send = True
'''
assert old in s
s = s.replace(old, new, 1)

old = '''    def _maybe_resume(self, channel):
        send = False
        with channel._recv_cond:
            if channel._flow_paused and \\
                    channel._recv_size <= self._low_water_mark:
                channel._flow_paused = False
                send = True
'''
new = '''    def _maybe_resume(self, channel):
        send = False
        with channel._recv_cond:
            total = channel._recv_size + len(channel.buffer)
            if channel._flow_paused and \\
                    total <= self._low_water_mark:
                channel._flow_paused = False
                send = True
'''
assert old in s
s = s.replace(old, new, 1)

open(path,'w').write(s)
print("flow control includes buffer")
PYEOF
python -c "import ast; ast.parse(open('/app/pwnlib/tubes/mux.py').read()); print('ok')"