cd /app && timeout 10 python - <<'EOF'
from pwnlib.tubes.tube import tube
from pwnlib.tubes.mux import TubeMultiplexer
t = tube()
m = t.mux()
print("isinstance", isinstance(m, TubeMultiplexer))
m.close()
EOF