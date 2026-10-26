cd /app && python - <<'PY'
path='pwnlib/tubes/mux.py'
src=open(path).read()

old = '''        self._reader_thread = context.Thread(target=self._read_loop, name='mux-reader')
        self._reader_thread.daemon = True
        self._reader_thread.start()
'''
new = '''        self._read_buffer = b''

        self._reader_thread = context.Thread(target=self._read_loop, name='mux-reader')
        self._reader_thread.daemon = True
        self._reader_thread.start()
'''
assert old in src
src = src.replace(old, new)

old = '''    def _read_frame(self):
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
new = '''    def _read_frame(self):
        """
        Reads and returns one complete ``(ftype, channel_id, payload)`` frame
        from the underlying tube.

        Uses short reads so that local closure can be observed promptly even
        when the underlying tube does not wake a blocked reader.
        """
        while not self._closed:
            frame = self._extract_frame()
            if frame is not None:
                return frame

            try:
                data = self._underlying.recv(4096, timeout=0.05)
            except EOFError:
                raise

            if data:
                self._read_buffer += data
            elif self._closed:
                break

        raise EOFError('multiplexer is closed')

    def _extract_frame(self):
        buf = self._read_buffer
        if len(buf) < _HEADER.size:
            return None
        length, ftype, channel_id = _HEADER.unpack(buf[:_HEADER.size])
        if length < 2:
            raise EOFError('invalid frame')
        total = _HEADER.size + (length - 2)
        if len(buf) < total:
            return None
        payload = buf[_HEADER.size:total]
        self._read_buffer = buf[total:]
        return ftype, channel_id, payload
'''
assert old in src
src = src.replace(old, new)
open(path,'w').write(src)
print('patched')
PY
python -m py_compile pwnlib/tubes/mux.py && echo OK