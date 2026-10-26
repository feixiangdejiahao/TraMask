cd /app && python - <<'PYEOF'
path = 'pwnlib/tubes/mux.py'
s = open(path).read()
s = s.replace('''        self._reader_thread.start()


    def _resolve_timeout(self, timeout):
''', '''        self._reader_thread.start()

    def _resolve_timeout(self, timeout):
''', 1)
open(path,'w').write(s)
print("cleaned")
PYEOF
python -c "import ast; ast.parse(open('/app/pwnlib/tubes/mux.py').read()); print('ok')"