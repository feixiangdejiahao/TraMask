cd /app && python - <<'PY'
path='pwnlib/tubes/mux.py'
src=open(path).read()

# Fix _read_frame to use local(None) so recvn blocks until EOF
old = '''    def _read_frame(self):
        header = self._underlying.recvn(_HEADER.size, timeout=None)
        if len(header) < _HEADER.size:
            raise EOFError('underlying tube closed')
        length, ftype, channel_id = _HEADER.unpack(header)
        payload_len = length - 2
        if payload_len < 0:
            raise EOFError('invalid frame')
        payload = b''
        if payload_len:
            payload = self._underlying.recvn(payload_len, timeout=None)
            if len(payload) < payload_len:
                raise EOFError('underlying tube closed')
        return ftype, channel_id, payload
'''
new = '''    def _read_frame(self):
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
assert old in src
src = src.replace(old, new)

# Fix close() join current thread
old = '''        # Give the reader thread a moment to notice the EOF, but do not block
        # forever if it is stuck.
        if self._reader_thread.is_alive():
            self._reader_thread.join(timeout=1.0)
'''
new = '''        # Give the reader thread a moment to notice the EOF, but do not block
        # forever if it is stuck.
        if self._reader_thread.is_alive() and self._reader_thread is not threading.current_thread():
            self._reader_thread.join(timeout=1.0)
'''
assert old in src
src = src.replace(old, new)

# Remove temporary traceback
src = src.replace('''        except Exception as e:
            import traceback; traceback.print_exc()
            log.debug('multiplexer reader error: %r', e)
''', '''        except Exception as e:
            log.debug('multiplexer reader error: %r', e)
''')
open(path,'w').write(src)
print('patched')
PY
python -m py_compile pwnlib/tubes/mux.py && python /tmp/test_mux.py 2>&1 | tail -30