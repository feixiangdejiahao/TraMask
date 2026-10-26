cd /app && python - <<'PYEOF'
path = 'pwnlib/tubes/mux.py'
s = open(path).read()
old = '''    def _handle_open(self, channel_id):
        if self._closed:
            return

        with self._channels_lock:
            if channel_id in self.channels:
                return
            if len(self.channels) >= self._max_channels:
                # Cannot accept another channel; reject the open request.
                try:
                    self._send_frame(channel_id, _MSG_NACK)
                except EOFError:
                    pass
                return
            channel = MuxChannel(self, channel_id)
            self.channels[channel_id] = channel

        try:
            self._send_frame(channel_id, _MSG_ACK)
        except EOFError:
            return

        with self._accept_cond:
            self._accept_queue.append(channel)
            self._accept_cond.notify_all()
'''
new = '''    def _handle_open(self, channel_id):
        if self._closed:
            return

        already_open = False
        with self._channels_lock:
            if channel_id in self.channels:
                # Both sides independently opened this channel.  Acknowledge
                # the peer's request using the channel we already have.
                already_open = True
            elif len(self.channels) >= self._max_channels:
                # Cannot accept another channel; reject the open request.
                try:
                    self._send_frame(channel_id, _MSG_NACK)
                except EOFError:
                    pass
                return
            else:
                channel = MuxChannel(self, channel_id)
                self.channels[channel_id] = channel

        if already_open:
            try:
                self._send_frame(channel_id, _MSG_ACK)
            except EOFError:
                pass
            return

        try:
            self._send_frame(channel_id, _MSG_ACK)
        except EOFError:
            return

        with self._accept_cond:
            self._accept_queue.append(channel)
            self._accept_cond.notify_all()
'''
assert old in s
s = s.replace(old, new, 1)
open(path,'w').write(s)
print("handle_open patched")
PYEOF
python -c "import ast; ast.parse(open('/app/pwnlib/tubes/mux.py').read()); print('ok')"