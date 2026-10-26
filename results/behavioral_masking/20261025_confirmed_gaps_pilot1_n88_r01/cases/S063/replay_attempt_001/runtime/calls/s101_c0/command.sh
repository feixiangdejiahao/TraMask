cd /app && python - <<'PYEOF'
path = 'pwnlib/tubes/mux.py'
s = open(path).read()

# In open_channel, after wait, check closed
old = '''        if not channel._open_event.wait(timeout):
            # Clean up the failed channel and tell the remote side to forget it.
            self._remove_channel(channel_id)
            try:
                self._send_frame(channel_id, _MSG_CLOSE)
            except EOFError:
                pass
            raise TimeoutError("timed out waiting for channel acknowledgement")

        if channel._open_failed:
'''
new = '''        if not channel._open_event.wait(timeout):
            # Clean up the failed channel and tell the remote side to forget it.
            self._remove_channel(channel_id)
            try:
                self._send_frame(channel_id, _MSG_CLOSE)
            except EOFError:
                pass
            raise TimeoutError("timed out waiting for channel acknowledgement")

        if self._closed:
            self._remove_channel(channel_id)
            raise EOFError("multiplexer is closed")

        if channel._open_failed:
'''
assert old in s
s = s.replace(old, new, 1)

# _mux_closed sets open_event
old = '''    def _mux_closed(self):
        with self._recv_cond:
            self._recv_eof = True
            self._recv_cond.notify_all()
        with self._send_cond:
            self._send_eof = True
            self._send_cond.notify_all()
'''
new = '''    def _mux_closed(self):
        with self._recv_cond:
            self._recv_eof = True
            self._recv_cond.notify_all()
        with self._send_cond:
            self._send_eof = True
            self._send_cond.notify_all()
        self._open_event.set()
'''
assert old in s
s = s.replace(old, new, 1)

open(path,'w').write(s)
print("patched open-chunk-on-close")
PYEOF
python -c "import ast; ast.parse(open('/app/pwnlib/tubes/mux.py').read()); print('ok')"