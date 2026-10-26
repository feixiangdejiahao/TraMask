cd /app && python - <<'PYEOF'
path = 'pwnlib/tubes/mux.py'
s = open(path).read()
old = '''    def recv_raw(self, numb):
        data = self._recv_data_chunk(self.timeout)
        if data is None:
            return None
        return data
'''
new = '''    def recv_raw(self, numb):
        data = self._recv_data_chunk(self.timeout)
        if data is None:
            return None
        self._mux._maybe_resume(self)
        return data
'''
assert old in s
s = s.replace(old, new, 1)
open(path,'w').write(s)
print("recv_raw resume patched")
PYEOF
python -c "import ast; ast.parse(open('/app/pwnlib/tubes/mux.py').read()); print('ok')"