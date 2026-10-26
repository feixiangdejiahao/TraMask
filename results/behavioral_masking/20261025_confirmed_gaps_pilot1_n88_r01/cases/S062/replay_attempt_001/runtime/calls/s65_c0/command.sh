cd /app && python - <<'PY'
path='pwnlib/tubes/buffer.py'
src=open(path).read()
old='''        if low is not None and high is not None and low > high:
            raise ValueError("low_water mark cannot exceed high_water mark")

        if high is not None:
            self.high_water = high
        if low is not None:
            self.low_water = low
'''
new='''        if high is not None and low is not None and low > high:
            raise ValueError("low_water mark cannot exceed high_water mark")

        self.high_water = high
        self.low_water = low
'''
assert old in src
src=src.replace(old,new,1)
open(path,'w').write(src)
print('buffer patched')
PY
python - <<'PY'
path='pwnlib/tubes/mux.py'
src=open(path).read()
src=src.replace("            ch._recv_buffer.set_watermarks(high=value)", "            ch._recv_buffer.set_watermarks(high=value, low=self._low_water_mark)")
src=src.replace("            ch._recv_buffer.set_watermarks(low=value)", "            ch._recv_buffer.set_watermarks(high=self._high_water_mark, low=value)")
open(path,'w').write(src)
print('mux patched')
PY
python -m py_compile pwnlib/tubes/buffer.py pwnlib/tubes/mux.py && python - <<'PY'
from pwnlib.tubes.buffer import Buffer
b=Buffer()
b.set_watermarks(high=10, low=5)
print(b.high_water, b.low_water)
b.set_watermarks(high=None)
print('after high=None:', b.high_water, b.low_water, b.over_high_water, b.under_low_water)
b.add(b'A'*10)
print(b.over_high_water)
b.set_watermarks(high=10, low=5)
try: b.set_watermarks(high=1, low=2)
except ValueError: print('ValueError ok')
PY