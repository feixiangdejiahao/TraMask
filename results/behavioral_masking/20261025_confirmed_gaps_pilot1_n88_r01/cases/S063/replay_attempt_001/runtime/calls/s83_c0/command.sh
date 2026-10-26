cd /app && timeout 15 python - <<'EOF'
from pwnlib.tubes.process import process
p = process(['/bin/cat'])
m = p.mux(max_channels=4)
print("mux over process ok", m.closed)
m.close()
p.close()
EOF