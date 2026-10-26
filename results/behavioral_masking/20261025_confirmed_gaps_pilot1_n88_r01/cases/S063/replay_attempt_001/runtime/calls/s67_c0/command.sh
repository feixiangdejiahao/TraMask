cd /app && python - <<'PYEOF'
path = 'pwnlib/tubes/mux.py'
s = open(path).read()

old = '''    def _reader_loop(self):
        try:
            while True:
                try:
                    header = self._underlying.recvn(_HDRLEN, timeout=Timeout.maximum)
                except EOFError:
                    break
                if not header or len(header) < _HDRLEN:
                    break

                channel_id, length = struct.unpack(_HDR_FMT, header)
                payload = self._underlying.recvn(length, timeout=Timeout.maximum)
                if payload is None or len(payload) < length:
                    break

                self._dispatch(channel_id, payload)
        except Exception:
            log.debug("TubeMultiplexer reader thread died", exc_info=True)
        finally:
            self._handle_underlying_eof()
'''
new = '''    def _reader_loop(self):
        try:
            while True:
                try:
                    header = self._underlying.recvn(_HDRLEN, timeout=_POLL_INTERVAL)
                except EOFError:
                    break
                if not header:
                    # recvn() timed out with no data.  Check whether the
                    # underlying tube has been closed out from under us, and
                    # if not keep polling.
                    if self._closed or self._underlying_dead():
                        break
                    continue
                if len(header) < _HDRLEN:
                    break

                channel_id, length = struct.unpack(_HDR_FMT, header)
                payload = self._underlying.recvn(length, timeout=Timeout.maximum)
                if payload is None or len(payload) < length:
                    break

                self._dispatch(channel_id, payload)
        except Exception:
            log.debug("TubeMultiplexer reader thread died", exc_info=True)
        finally:
            self._handle_underlying_eof()

    def _underlying_dead(self):
        """Best-effort check for whether the underlying tube has been closed."""
        underlying = self._underlying
        closed = getattr(underlying, "closed", None)
        if isinstance(closed, dict):
            return bool(closed.get("recv") or closed.get("send"))
        if closed is True:
            return True
        try:
            if hasattr(underlying, "proc"):
                return not underlying.connected()
        except Exception:
            pass
        return False
'''
assert old in s
s = s.replace(old, new, 1)

# Add poll interval constant near top
s = s.replace('''_MAX_CHANNEL_ID = 65535
''', '''_MAX_CHANNEL_ID = 65535

# How often the reader thread wakes up to check for a closed underlying tube.
_POLL_INTERVAL = 0.1
''', 1)

open(path,'w').write(s)
print("reader patched")
PYEOF
python -c "import ast; ast.parse(open('/app/pwnlib/tubes/mux.py').read()); print('ok')"