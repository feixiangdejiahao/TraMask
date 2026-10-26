cd /app && python - <<'PYEOF'
path = 'pwnlib/tubes/mux.py'
s = open(path).read()

# Add _MSG_MUX_CLOSE
s = s.replace("""_MSG_FIN    = 8   # Half-close: local send direction is finished
""", """_MSG_FIN    = 8   # Half-close: local send direction is finished
_MSG_MUX_CLOSE = 9  # The whole multiplexer is being closed
""")

# Update close()
old_close = '''    def close(self):
        """Close the multiplexer and all channels.

        Signals EOF to every channel, closes the underlying tube, and is
        idempotent.  Threads blocked in :meth:`accept_channel` are woken up
        with :class:`EOFError`.
        """
        with self._closed_cond:
            if self._closed:
                return
            self._closed = True
            self._closed_cond.notify_all()

        with self._channels_lock:
            channels = list(self.channels.values())
            self.channels.clear()

        for channel in channels:
            channel._mux_closed()

        with self._accept_cond:
            self._accept_cond.notify_all()

        try:
            self._underlying.close()
        except Exception:
            pass
'''
new_close = '''    def close(self):
        """Close the multiplexer and all channels.

        Signals EOF to every channel, closes the underlying tube, and is
        idempotent.  Threads blocked in :meth:`accept_channel` are woken up
        with :class:`EOFError`.
        """
        with self._closed_cond:
            if self._closed:
                return

        # Tell the peer that the entire multiplexer is closing, so that it
        # can detect the closure even if the underlying tube's EOF is delayed.
        try:
            self._send_frame(0, _MSG_MUX_CLOSE)
        except Exception:
            pass

        with self._closed_cond:
            if self._closed:
                return
            self._closed = True
            self._closed_cond.notify_all()

        with self._channels_lock:
            channels = list(self.channels.values())
            self.channels.clear()

        for channel in channels:
            channel._mux_closed()

        with self._accept_cond:
            self._accept_cond.notify_all()

        # Wake our own reader thread and signal EOF to the peer.  A blocked
        # recv() is woken by shutting down the socket, whereas merely calling
        # close() may leave the reader thread stuck in recv().
        try:
            self._underlying.shutdown("send")
        except Exception:
            pass
        try:
            self._underlying.shutdown("recv")
        except Exception:
            pass
        try:
            self._underlying.close()
        except Exception:
            pass
'''
assert old_close in s
s = s.replace(old_close, new_close, 1)

# Add dispatch case
old_dispatch = '''        elif msgtype == _MSG_RESUME:
            self._handle_resume(channel_id)
'''
new_dispatch = '''        elif msgtype == _MSG_RESUME:
            self._handle_resume(channel_id)
        elif msgtype == _MSG_MUX_CLOSE:
            self._handle_underlying_eof()
'''
assert old_dispatch in s
s = s.replace(old_dispatch, new_dispatch, 1)

open(path, 'w').write(s)
print("patched")
PYEOF
python -c "import ast; ast.parse(open('/app/pwnlib/tubes/mux.py').read()); print('ok')"