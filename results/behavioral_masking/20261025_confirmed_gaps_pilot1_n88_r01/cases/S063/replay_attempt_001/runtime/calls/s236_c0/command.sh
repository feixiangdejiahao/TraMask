cd /app && timeout 15 python - <<'EOF'
from pwnlib.tubes.buffer import Buffer
b=Buffer()
b.set_watermarks(high=10, low=5)
b.add(b'hello')
print(len(b), b.over_high_water, b.under_low_water)
print(b.get())
print("buffer ok")
EOF