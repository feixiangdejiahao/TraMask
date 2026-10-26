cd /app && python - <<'PYEOF'
path = 'pwnlib/tubes/mux.py'
s = open(path).read()
old = '''                channel_id, length = struct.unpack(_HDR_FMT, header)
                payload = self._underlying.recvn(length, timeout=Timeout.maximum)
                if payload is None or len(payload) < length:
                    break

                self._dispatch(channel_id, payload)
'''
new = '''                channel_id, length = struct.unpack(_HDR_FMT, header)
                while True:
                    payload = self._underlying.recvn(length, timeout=_POLL_INTERVAL)
                    if payload and len(payload) >= length:
                        break
                    if self._closed or self._underlying_dead():
                        raise EOFError("underlying tube closed while reading frame")

                self._dispatch(channel_id, payload)
'''
assert old in s
s = s.replace(old, new, 1)
open(path,'w').write(s)
print("payload read patched")
PYEOF
python -c "import ast; ast.parse(open('/app/pwnlib/tubes/mux.py').read()); print('ok')"