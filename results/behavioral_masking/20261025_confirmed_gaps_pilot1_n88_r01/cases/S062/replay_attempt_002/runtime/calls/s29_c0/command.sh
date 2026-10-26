cd /app && python - <<'PY'
path='pwnlib/tubes/mux.py'
src=open(path).read()
old = '''    def _read_frame(self):
        with self._underlying.local(None):
            header = self._underlying.recvn(_HEADER.size)
            if len(header) < _HEADER.size:
                raise EOFError('underlying tube closed')
            length, ftype, channel_id = _HEADER.unpack(header)
            payload_len = length - 2
            if payload_len < 0:
                raise EOFError('invalid frame')
            payload = b''
            if payload_len:
                payload = self._underlying.recvn(payload_len)
                if len(payload) < payload_len:
                    raise EOFError('underlying tube closed')
        return ftype, channel_id, payload
'''
new = '''    def _read_frame(self):
        forever = self._underlying.maximum
        header = self._underlying.recvn(_HEADER.size, timeout=forever)
        if len(header) < _HEADER.size:
            raise EOFError('underlying tube closed')
        length, ftype, channel_id = _HEADER.unpack(header)
        payload_len = length - 2
        if payload_len < 0:
            raise EOFError('invalid frame')
        payload = b''
        if payload_len:
            payload = self._underlying.recvn(payload_len, timeout=forever)
            if len(payload) < payload_len:
                raise EOFError('underlying tube closed')
        return ftype, channel_id, payload
'''
assert old in src
src = src.replace(old, new)
open(path,'w').write(src)
print('patched')
PY
python /tmp/test_mux.py 2>&1 | tail -30