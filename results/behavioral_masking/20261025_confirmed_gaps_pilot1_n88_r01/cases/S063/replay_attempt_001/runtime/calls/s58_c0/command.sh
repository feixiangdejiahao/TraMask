cd /app && python - <<'PYEOF'
path = 'pwnlib/tubes/mux.py'
s = open(path).read()

old = '''    @property
    def high_water_mark(self):
        return self._high_water_mark

    @property
    def low_water_mark(self):
        return self._low_water_mark
'''
new = '''    @property
    def high_water_mark(self):
        return self._high_water_mark

    @high_water_mark.setter
    def high_water_mark(self, value):
        if value < self._low_water_mark:
            raise ValueError("high_water_mark cannot be below low_water_mark")
        self._high_water_mark = value

    @property
    def low_water_mark(self):
        return self._low_water_mark

    @low_water_mark.setter
    def low_water_mark(self, value):
        if value > self._high_water_mark:
            raise ValueError("low_water_mark cannot exceed high_water_mark")
        self._low_water_mark = value
'''
assert old in s
s = s.replace(old, new, 1)
open(path,'w').write(s)
print("setters added")
PYEOF
python -c "import ast; ast.parse(open('/app/pwnlib/tubes/mux.py').read()); print('ok')"