cd /app && python - <<'PYEOF'
path = 'pwnlib/tubes/mux.py'
s = open(path).read()
s = s.replace('''    @high_water_mark.setter
    def high_water_mark(self, value):
        if value < self._low_water_mark:
            raise ValueError("high_water_mark cannot be below low_water_mark")
        self._high_water_mark = value
''', '''    @high_water_mark.setter
    def high_water_mark(self, value):
        self._high_water_mark = value
''')
s = s.replace('''    @low_water_mark.setter
    def low_water_mark(self, value):
        if value > self._high_water_mark:
            raise ValueError("low_water_mark cannot exceed high_water_mark")
        self._low_water_mark = value
''', '''    @low_water_mark.setter
    def low_water_mark(self, value):
        self._low_water_mark = value
''')
open(path,'w').write(s)
print("lenient setters")
PYEOF
python - <<'EOF'
import ast; ast.parse(open('/app/pwnlib/tubes/mux.py').read()); print('ok')
EOF