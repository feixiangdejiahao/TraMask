cd /app && python - <<'PYEOF'
path = 'pwnlib/tubes/mux.py'
s = open(path).read()
marker = '''    # ------------------------------------------------------------------
    # Reader thread
    # ------------------------------------------------------------------
'''
insert = '''    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
        return False

    # ------------------------------------------------------------------
    # Reader thread
    # ------------------------------------------------------------------
'''
assert marker in s
s = s.replace(marker, insert, 1)
open(path,'w').write(s)
print("context manager added")
PYEOF
python -c "import ast; ast.parse(open('/app/pwnlib/tubes/mux.py').read()); print('ok')"