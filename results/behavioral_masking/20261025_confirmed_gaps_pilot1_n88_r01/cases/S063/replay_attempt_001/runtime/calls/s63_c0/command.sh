cd /app && python - <<'PYEOF'
path = 'pwnlib/tubes/buffer.py'
s = open(path).read()
old = '''        if high is not None:
            self.high_water = high
        if low is not None:
            self.low_water = low
        if (self.high_water is not None and self.low_water is not None
                and self.low_water > self.high_water):
            raise ValueError("low_water_mark cannot exceed high_water_mark")
'''
new = '''        new_high = self.high_water if high is None else high
        new_low = self.low_water if low is None else low
        if new_high is not None and new_low is not None and new_low > new_high:
            raise ValueError("low_water_mark cannot exceed high_water_mark")
        if high is not None:
            self.high_water = high
        if low is not None:
            self.low_water = low
'''
assert old in s
s = s.replace(old, new, 1)
open(path,'w').write(s)
print("patched atomic")
PYEOF
python - <<'EOF'
from pwnlib.tubes.buffer import Buffer
b = Buffer()
b.set_watermarks(high=10, low=5)
print(b.high_water, b.low_water)
try:
    b.set_watermarks(high=3)
except ValueError:
    print("ValueError ok; state:", b.high_water, b.low_water)
EOF