cd /app && python - <<'PY'
path = 'pwnlib/tubes/mux.py'
src = open(path).read()

# Remove leftover recv_raw_loop method
src = src.replace('''
    # The reader thread of the multiplexer is responsible for receiving.
    def recv_raw_loop(self):
        raise NotImplementedError()
''', '\n')

# Fix _handle_open: avoid holding lock while writing
old = '''    def _handle_open(self, channel_id):
        with self._lock:
            if self._closed:
                return
            if channel_id in self.channels or channel_id in self._closing_ids:
                self._write_frame(_NAK, channel_id)
                return
            if len(self.channels) >= self._max_channels:
                self._write_frame(_NAK, channel_id)
                return

            ch = MuxChannel(self, channel_id)
            self.channels[channel_id] = ch
            self._pending_accept.append(ch)

            with self._accept_cond:
                self._accept_cond.notify_all()

        try:
            self._write_frame(_ACK, channel_id)
        except EOFError:
            pass
'''
new = '''    def _handle_open(self, channel_id):
        reject = False
        with self._lock:
            if self._closed:
                return
            if channel_id in self.channels or channel_id in self._closing_ids:
                reject = True
            elif len(self.channels) >= self._max_channels:
                reject = True
            else:
                ch = MuxChannel(self, channel_id)
                self.channels[channel_id] = ch
                self._pending_accept.append(ch)
                with self._accept_cond:
                    self._accept_cond.notify_all()

        if reject:
            try:
                self._write_frame(_NAK, channel_id)
            except EOFError:
                pass
            return

        try:
            self._write_frame(_ACK, channel_id)
        except EOFError:
            pass
'''
assert old in src
src = src.replace(old, new)

# Fix can_recv_raw
old = '''    def can_recv_raw(self, timeout=0):
        deadline = None
        if timeout is not None and timeout != 0:
            deadline = time.monotonic() + timeout
        with self._cond:
            while not self._recv_buffer and not self._recv_eof and not self._closed:
                if deadline is None or timeout == 0:
                    return False
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                self._cond.wait(remaining)
            return bool(self._recv_buffer) or self._recv_eof
'''
new = '''    def can_recv_raw(self, timeout=0):
        deadline = None
        if timeout is not None:
            deadline = time.monotonic() + timeout
        with self._cond:
            while not self._recv_buffer and not self._recv_eof and not self._closed:
                if deadline is None:
                    self._cond.wait()
                    continue
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                self._cond.wait(remaining)
            return bool(self._recv_buffer) or self._recv_eof
'''
assert old in src
src = src.replace(old, new)

open(path, 'w').write(src)
print('patched')
PY
python -m py_compile pwnlib/tubes/mux.py && echo OK