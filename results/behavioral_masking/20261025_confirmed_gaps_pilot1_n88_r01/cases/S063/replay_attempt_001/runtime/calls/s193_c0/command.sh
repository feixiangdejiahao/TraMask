cd /app && python - <<'EOF'
from pwnlib.tubes.buffer import Buffer
b=Buffer()
b.set_watermarks(high=10, low=5)
try:
    b.set_watermarks(high=3, low=7)
except ValueError:
    pass
print(b.high_water, b.low_water)
assert b.high_water==10 and b.low_water==5
print("atomic ok")
EOF