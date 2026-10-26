cd /app && python - <<'PY'
from pwnlib.tubes.buffer import Buffer
b = Buffer()
print(b.over_high_water, b.under_low_water)
b.set_watermarks(high=10, low=5)
print(b.high_water, b.low_water, b.over_high_water, b.under_low_water)
b.add(b'A'*10)
print(b.over_high_water, b.under_low_water)
b.add(b'B'*3)
print(b.over_high_water, b.under_low_water)
b.get(8)
print('size', len(b), b.over_high_water, b.under_low_water)
b.get()
print('size', len(b), b.over_high_water, b.under_low_water)
try:
    b.set_watermarks(high=5, low=10)
except ValueError as e:
    print('ValueError ok')
# test setting only one
c=Buffer(); c.set_watermarks(high=3); print(c.over_high_water, c.under_low_water)
c.add(b'xx'); print(c.over_high_water, c.under_low_water)
PY