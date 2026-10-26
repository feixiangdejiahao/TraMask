cd /app && python - <<'PYEOF'
path = 'pwnlib/tubes/mux.py'
s = open(path).read()
old = '''    def can_recv_raw(self, timeout):
        with self._recv_cond:
            if self._recv_queue:
                return True
            if self._recv_eof:
                return False
            if timeout:
                self._recv_cond.wait(timeout)
            return bool(self._recv_queue)
'''
new = '''    def can_recv_raw(self, timeout):
        with self._recv_cond:
            if self._recv_queue:
                return True
            if self._recv_eof:
                return False
            if timeout is None:
                while not self._recv_queue and not self._recv_eof:
                    self._recv_cond.wait()
            elif timeout:
                self._recv_cond.wait(timeout)
            return bool(self._recv_queue)
'''
assert old in s
s = s.replace(old, new, 1)
open(path,'w').write(s)
print("can_recv_raw None handled")
PYEOF
python -c "import ast; ast.parse(open('/app/pwnlib/tubes/mux.py').read()); print('ok')"